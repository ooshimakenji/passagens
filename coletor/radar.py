"""Radar de passagens: varre os setups do config.json e grava o JSON que a SPA lê.

Roda no GitHub Actions (ou local, pelo .bat) e não precisa de servidor nem banco — mesmo
desenho do `licitacoes`: o histórico vive num branch órfão `dados`.

O que ele faz que o alerta do Google Flights e do Skyscanner não fazem:
  - guarda-chuva: destino pode ser um país, expandido para as cidades dele;
  - gatilho meu: teto em reais OU percentual abaixo da mediana histórica da rota;
  - histórico próprio, que é o que permite dizer "abaixo da mediana".
"""

from __future__ import annotations

import csv
import json
import os
import statistics
import subprocess
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

from extrator import extrair_voos, mais_barato
from fast_flights import FlightQuery, Passengers, create_query
from primp import Client  # já vem com o fast-flights; é o cliente que ele usa internamente

RAIZ = Path(__file__).resolve().parent.parent
CACHE = Path(__file__).resolve().parent / "cache"

# Duas tabelas públicas e sem token, cada uma pelo que a outra não tem: a Travelpayouts dá
# o código de CIDADE (buscar `TYO` cobre Haneda e Narita de uma vez, `SAO` cobre
# GRU+CGH+VCP) e a OurAirports (CC0) dá o PORTE real do aeroporto, que é o que separa
# Fukuoka de Asahikawa. Só com o nome ("International") a escolha saía errada.
AEROPORTOS_URL = "https://api.travelpayouts.com/data/en/airports.json"
PORTE_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"

_PORTE = {"large_airport": 2, "medium_airport": 1}

BUSCA_URL = "https://www.google.com/travel/flights/search"
# "show all flights and prices condition". Sem ele o Google devolve a lista TRUNCADA:
# medido em 2026-10-04, SAO->TYO passou de 11 para 96 itinerários e SAO->PVG de 13 para 48,
# pela mesma busca. Foi perdido no rewrite 3.0 do fast-flights e restaurado no PR #115
# (mergeado 2026-09-21), mas o PyPI ainda publica a 3.1.0 sem ele — por isso montamos a
# requisição aqui em vez de usar o `fetch_flights_html` da lib.
TFU = "EgQIABABIgA"

# O mesmo disfarce que o fast-flights usa internamente.
_cliente = Client(impersonate="chrome_145", impersonate_os="macos")


def buscar_html(q) -> str:
    return _cliente.get(
        BUSCA_URL, params={"tfs": q.to_str(), "curr": "BRL", "hl": "", "tfu": TFU}
    ).text


# --------------------------------------------------------------------------- guarda-chuva


def _baixar(url: str, nome: str) -> Path:
    """Cacheia em disco: as duas tabelas mudam uma vez por ano e somam 15 MB — o job não
    tem por que baixar isso a cada execução."""
    CACHE.mkdir(exist_ok=True)
    arq = CACHE / nome
    if not arq.exists():
        with urllib.request.urlopen(url, timeout=120) as r:
            arq.write_bytes(r.read())
    return arq


def _portes() -> dict[str, int]:
    """IATA -> peso de porte, só para aeroporto com voo regular."""
    pesos = {}
    with _baixar(PORTE_URL, "ourairports.csv").open(encoding="utf-8", newline="") as f:
        for a in csv.DictReader(f):
            if a["scheduled_service"] == "yes" and a["iata_code"]:
                pesos[a["iata_code"]] = _PORTE.get(a["type"], 0)
    return pesos


@lru_cache(maxsize=1)
def _mapa_paises() -> tuple[dict[str, str], dict[str, str]]:
    """(nome do aeroporto -> país, cidade -> país), das duas tabelas juntas.

    O rótulo do Google dá a escala por extenso ("John F. Kennedy International Airport in
    New York"), nunca por código. Para saber se uma conexão exige visto é preciso voltar
    desse texto para o país, e nenhuma tabela sozinha cobre: a Travelpayouts grafa nomes
    que a OurAirports escreve diferente e vice-versa.
    """
    por_nome: dict[str, str] = {}
    por_cidade: dict[str, str] = {}

    for a in json.loads(_baixar(AEROPORTOS_URL, "airports.json").read_text(encoding="utf-8")):
        pais = a.get("country_code")
        if not pais:
            continue
        for nome in {a.get("name"), (a.get("name_translations") or {}).get("en")}:
            if nome:
                por_nome.setdefault(nome.strip(), pais)

    # Cidade homônima é uma armadilha séria aqui: "Paris" aparece 36 vezes nos Estados
    # Unidos (Texas, Tennessee) e Charles de Gaulle sequer está registrado sob o município
    # "Paris". Mapear cidade pelo primeiro que aparece diria que um voo via Paris exige
    # visto americano. Por isso a cidade só resolve o país quando TODOS os aeroportos com
    # voo regular que levam aquele nome estão no mesmo país; havendo dúvida, fica sem país.
    candidatos: dict[str, set[str]] = {}
    with _baixar(PORTE_URL, "ourairports.csv").open(encoding="utf-8", newline="") as f:
        for a in csv.DictReader(f):
            pais = a["iso_country"]
            if a["name"]:
                por_nome.setdefault(a["name"].strip(), pais)
            if a["municipality"] and a["scheduled_service"] == "yes":
                candidatos.setdefault(a["municipality"].strip(), set()).add(pais)

    por_cidade = {c: next(iter(p)) for c, p in candidatos.items() if len(p) == 1}
    return por_nome, por_cidade


def pais_da_escala(aeroporto: str | None, cidade: str | None) -> str | None:
    """País de uma escala, ou None quando nenhuma tabela reconhece o nome.

    None é tratado como desconhecido, nunca como "não é país nenhum": dizer que um voo
    não passa pelos EUA quando na verdade não se sabe seria o erro caro aqui.
    """
    por_nome, por_cidade = _mapa_paises()
    if aeroporto and aeroporto.strip() in por_nome:
        return por_nome[aeroporto.strip()]
    if cidade and cidade.strip() in por_cidade:
        return por_cidade[cidade.strip()]
    return None


def paises_de_escala(voo) -> tuple[list[str], list[str]]:
    """(países reconhecidos nas escalas, escalas que ficaram sem país)."""
    paises, desconhecidas = [], []
    for _minutos, aeroporto, cidade in voo.escalas:
        p = pais_da_escala(aeroporto, cidade)
        if p:
            if p not in paises:
                paises.append(p)
        else:
            desconhecidas.append(cidade or aeroporto)
    return paises, desconhecidas


def expandir(alvo: str | list[str], max_cidades: int) -> list[str]:
    """Resolve o guarda-chuva em códigos que o Google Flights aceita.

    - 3 letras (`SAO`, `GRU`, `TYO`) -> usada como está. Código de cidade já é guarda-chuva
      nativo e vale uma busca só;
    - 2 letras (`JP`) -> país: expande para as cidades mais relevantes dele. O Google
      **não** aceita país (`SAO->JP` devolveu zero resultados em 2026-10-04), e é por isso
      que esta função existe — nenhum alerta pronto cobre "o Japão inteiro";
    - lista -> cada item resolvido pela mesma regra e concatenado, então
      `["JP", "KR", "TW"]` compara Japão, Coreia e Taiwan num setup só. Duplicata entre
      dois itens é descartada (sem repetir busca), mantendo a ordem.
    """
    if isinstance(alvo, list):
        vistos = {}
        for item in alvo:
            for codigo in expandir(item, max_cidades):
                vistos[codigo] = None  # dict preserva ordem e deduplica
        return list(vistos)
    if len(alvo) != 2:
        return [alvo]

    portes = _portes()
    cidades: dict[str, int] = {}
    for a in json.loads(_baixar(AEROPORTOS_URL, "airports.json").read_text(encoding="utf-8")):
        if a.get("country_code") != alvo.upper() or not a.get("flightable"):
            continue
        if a["code"] not in portes:  # sem voo regular não interessa
            continue
        cidade = a.get("city_code") or a["code"]
        cidades[cidade] = max(cidades.get(cidade, 0), portes[a["code"]])

    ordenadas = sorted(cidades, key=lambda c: (-cidades[c], c))
    if max_cidades:
        ordenadas = ordenadas[:max_cidades]
    print(f"  país {alvo} -> {len(cidades)} cidades com voo regular, {len(ordenadas)} na sonda")
    return ordenadas


def amostrar(faixa: list[int]) -> list[int]:
    """Mínimo, meio e máximo de uma faixa de dias. Varrer todo valor entre 10 e 20 dias
    multiplicaria as buscas por 11 para diferenças de preço que quase sempre aparecem já
    nos extremos."""
    return sorted({min(faixa), (min(faixa) + max(faixa)) // 2, max(faixa)})


def datas(meses: list[str], estadias: list[int], passo: int) -> list[tuple[str, str]]:
    """Pares (ida, volta) dentro dos meses pedidos.

    Varrer mês inteiro × toda estadia explode (31 × 11 = 341 buscas por rota), então
    amostra: ida a cada `passo` dias e só os extremos e o meio da faixa de estadia.
    """
    estadias = amostrar(estadias)
    hoje = date.today()
    pares = []
    for mes in meses:
        inicio = datetime.strptime(mes, "%Y-%m").date()
        fim = (inicio + timedelta(days=31)).replace(day=1)
        dia = inicio
        while dia < fim:
            if dia > hoje:  # o Google não cota passado
                for n in estadias:
                    pares.append((dia.isoformat(), (dia + timedelta(days=n)).isoformat()))
            dia += timedelta(days=passo)
    return pares


# --------------------------------------------------------------------------- busca


def consultar(origem, destino, ida, volta, max_paradas, tentativas=2, pausa=2):
    """Menor preço de ida-volta para essa combinação, ou None.

    Sempre ida-volta: o preço de ida-volta não é a soma de duas buscas de só ida
    (SAO->TYO em 2026-12-10 deu 4643 só ida contra 7927 ida-volta).

    Repete quando vem vazio porque o Google às vezes devolve a página sem os resultados:
    numa varredura de 72 cidades, SAO->TYO voltou vazio e, consultado sozinho em seguida,
    deu 7690 seis vezes seguidas. Página vazia e rota inexistente têm o MESMO HTML (nenhum
    texto do tipo "no flights"), então não há como distinguir a não ser tentando de novo —
    e um falso negativo aqui descarta uma cidade boa do radar.
    """
    q = create_query(
        flights=[
            FlightQuery(date=ida, from_airport=origem, to_airport=destino),
            FlightQuery(date=volta, from_airport=destino, to_airport=origem),
        ],
        seat="economy",
        trip="round-trip",
        passengers=Passengers(adults=1),
        currency="BRL",
        max_stops=max_paradas,
    )
    for tentativa in range(tentativas):
        voo = mais_barato(extrair_voos(buscar_html(q)))
        if voo is not None:
            # O link também leva o tfu: clicar e ver a lista truncada seria pior que
            # inútil — o preço da tela poderia não estar lá.
            return voo, f"{q.url()}&tfu={TFU}"
        if tentativa + 1 < tentativas:
            time.sleep(pausa * (tentativa + 2))  # a segunda espera é maior que a primeira
    return None


# --------------------------------------------------------------------------- gatilho


def sondar(origens, destinos, par, max_paradas, top, orcamento, pausa, mortas, hoje,
           historico=None, tentativas=3):
    """Fase 1 de "qualquer lugar do país": uma busca por destino, numa data representativa,
    só para ranquear as cidades pelo preço REAL e aprofundar nas mais baratas.

    Existe porque adivinhar quais cidades importam não funciona: a OurAirports marca 28
    aeroportos japoneses como `large_airport`, então porte não desempata e Tóquio ficava
    de fora de um top 6 alfabético. Preço desempata.

    Devolve (destinos escolhidos, ofertas da sonda, buscas gastas) — as sondas são preços
    reais e entram no resultado, não se joga fora.
    """
    precos, ofertas, gastas = {}, [], 0
    ida, volta = par
    for o in origens:
        for d in destinos:
            if gastas >= orcamento:
                break
            if esta_morta(mortas, f"{o}-{d}", hoje):
                continue
            gastas += 1
            try:
                # Mais tentativas aqui que na varredura: um vazio na sonda não custa uma
                # data, custa a cidade inteira — foi assim que Tóquio ficou de fora.
                achado = consultar(o, d, ida, volta, max_paradas, tentativas, pausa)
            except Exception as e:
                print(f"  sonda {o}-{d}: falhou ({type(e).__name__})", file=sys.stderr)
                continue
            finally:
                time.sleep(pausa)
            chave = f"{o}-{d}"
            marcar(mortas, chave, achado is not None, hoje, bool((historico or {}).get(chave)))
            if achado is None:
                continue  # Google não cota essa cidade a partir daqui: fora do radar
            voo, url = achado
            precos[d] = min(precos.get(d, voo.preco), voo.preco)
            ofertas.append((o, d, ida, volta, voo, url))

    escolhidos = sorted(precos, key=lambda d: precos[d])[:top]
    print(f"  sonda: {len(precos)}/{len(destinos)} cidades com voo, "
          f"aprofundando {[(d, precos[d]) for d in escolhidos]}")
    return escolhidos, ofertas, gastas


def cotar_stopover(origem, hub, destino, ida, volta, dias, max_paradas, cache, pausa):
    """Roteiro com parada de DIAS no meio do caminho, montado com **dois bilhetes**.

    O multi-city do Google não serve: a página de `trip="multi-city"` volta sem resultado
    no HTML, 5 tentativas de 5 (medido 2026-10-04, tamanho idêntico — não é a
    intermitência de página vazia, simplesmente não vem). Então o roteiro é cotado como
    as pessoas de fato compram:

        bilhete 1: origem <-> hub      (ida e volta nas datas do período)
        bilhete 2: hub    <-> destino  (sai `dias` depois de chegar, volta `dias` antes)

    Você acaba passando pelo hub na ida **e** na volta, o que é o efeito desejado. Em
    troca são dois contratos separados: atraso no primeiro não obriga ninguém a
    reacomodar no segundo. Quem usa precisa saber — vai marcado em `dois_bilhetes`.

    O bilhete 1 não depende de `dias`, então entra em `cache` e é cotado uma vez por
    (hub, par de datas), não uma vez por combinação.
    """
    chave = (origem, hub, ida, volta)
    if chave not in cache:
        cache[chave] = consultar(origem, hub, ida, volta, max_paradas, pausa=pausa)
        time.sleep(pausa)
    perna1 = cache[chave]
    if perna1 is None:
        return None

    ida2 = (date.fromisoformat(ida) + timedelta(days=dias)).isoformat()
    volta2 = (date.fromisoformat(volta) - timedelta(days=dias)).isoformat()
    if ida2 >= volta2:  # a parada comeu a viagem inteira
        return None

    perna2 = consultar(hub, destino, ida2, volta2, max_paradas, pausa=pausa)
    time.sleep(pausa)
    if perna2 is None:
        return None

    voo1, url1 = perna1
    voo2, url2 = perna2
    return {
        "preco": voo1.preco + voo2.preco,
        "hub": hub,
        "dias_no_hub": dias,
        # Lido na tela. `hub` é só a primeira parada: quem decide o sentido da viagem é
        # quem chama, trocando os papéis (ver `ORDENS` no main).
        "roteiro": f"{origem} → {hub} ({dias}d) → {destino} → {hub} → {origem}",
        "pernas": [
            {"trecho": f"{origem}-{hub}", "ida": ida, "volta": volta,
             "preco": voo1.preco, "cia": voo1.cia, "url": url1},
            {"trecho": f"{hub}-{destino}", "ida": ida2, "volta": volta2,
             "preco": voo2.preco, "cia": voo2.cia, "url": url2},
        ],
    }


def disparou(preco: int, mediana: float | None, gatilho: dict) -> tuple[bool, str | None]:
    """O setup disparou? Devolve (sim/não, motivo).

    Os dois critérios são independentes e qualquer um basta; omitir um no config desliga
    aquele critério. Sem histórico, só o teto vale — a mediana da primeira execução seria
    o próprio preço e nunca dispararia.
    """
    teto = gatilho.get("teto_brl")
    if teto is not None and preco <= teto:
        return True, f"abaixo do teto de R$ {teto}"

    pct = gatilho.get("pct_abaixo_mediana")
    if pct is not None and mediana is not None:
        limite = mediana * (1 - pct / 100)
        if preco <= limite:
            return True, f"{pct}% abaixo da mediana histórica (R$ {mediana:.0f})"

    return False, None


def mediana_rota(historico: dict, chave: str) -> float | None:
    # ponytail: mediana simples de todas as observações da rota. Trocar por desvio-padrão
    # ou janela móvel se aparecer falso-positivo em rota sazonal.
    serie = [p for _, p in historico.get(chave, [])]
    return statistics.median(serie) if len(serie) >= 3 else None


VAZIOS_PARA_MORRER = 3
DIAS_DE_DESCANSO = 30


def esta_morta(mortas: dict, chave: str, hoje: str) -> bool:
    """Rota que veio vazia muitas vezes seguidas sai da sonda por um tempo.

    Sem isso, o retry custaria 3 buscas por dia em cada cidade sem rota — e das 72
    cidades japonesas com voo regular, só um punhado tem ligação com São Paulo. Uma
    sonda de 72 cidades viraria 216 buscas diárias para descobrir o mesmo "não tem".
    """
    prazo = mortas.get(chave, {}).get("pular_ate")
    return bool(prazo and hoje < prazo)


def marcar(mortas: dict, chave: str, achou: bool, hoje: str, tem_historico=False) -> dict:
    """Conta vazios consecutivos; achar preço ressuscita a rota na hora.

    `tem_historico` protege o caso que já aconteceu de verdade: na coleta de 2026-10-04 no
    Actions, `SAO-TYO` voltou vazia na varredura das 72 cidades e o radar publicou Osaka a
    R$ 8.919 enquanto Tóquio, medida isolada, estava a R$ 7.690. Rota que **já deu preço
    algum dia** não é rota inexistente — então ela nunca é posta para dormir, só conta os
    vazios. Quem dorme é a cidade que nunca cotou nada.
    """
    if achou:
        mortas.pop(chave, None)
        return mortas
    reg = mortas.setdefault(chave, {"vazios": 0})
    reg["vazios"] += 1
    if reg["vazios"] >= VAZIOS_PARA_MORRER and not tem_historico:
        reg["pular_ate"] = (
            date.fromisoformat(hoje) + timedelta(days=DIAS_DE_DESCANSO)
        ).isoformat()
    return mortas


def minimo_por_rota(achados) -> dict[str, int]:
    minimos: dict[str, int] = {}
    for o, d, _ida, _volta, voo, _url, _sonda in achados:
        chave = f"{o}-{d}"
        minimos[chave] = min(minimos.get(chave, voo.preco), voo.preco)
    return minimos


def podar(historico: dict, dias: int) -> dict:
    corte = (date.today() - timedelta(days=dias)).isoformat()
    return {k: [[d, p] for d, p in v if d >= corte] for k, v in historico.items()}


# --------------------------------------------------------------------------- alerta


def avisar(disparos: list[dict]) -> None:
    """Abre uma issue no próprio repo. O GitHub já notifica por e-mail e no app do
    celular — sem bot de Telegram, sem SMTP, sem secret novo. Fora do Actions (ou sem o
    `gh`), só imprime: rodar local não deve criar issue sem querer."""
    def trajeto(d: dict) -> str:
        """Um roteiro com parada de dias não é "SAO→TYO": dizer isso no alerta esconde
        que são dois bilhetes e que a viagem passa por outro país."""
        sv = d.get("stopover")
        if sv:
            return f"{sv['roteiro']} (2 bilhetes)"
        return f"{d['origem']}→{d['destino']}"

    if not disparos or not os.environ.get("GITHUB_ACTIONS"):
        for d in disparos:
            print(f"  ALERTA {d['setup']}: R$ {d['preco']} {trajeto(d)} "
                  f"{d['ida']} a {d['volta']} ({d['motivo']})")
        return

    titulo = f"Promo: {len(disparos)} oferta(s) abaixo do gatilho — {date.today().isoformat()}"
    corpo = "\n".join(
        f"- **R$ {d['preco']}** · {d['setup']} · {trajeto(d)} · "
        f"{d['ida']} a {d['volta']} · {d['cia'] or '?'} · {d['motivo']}\n  {d['url']}"
        for d in disparos
    )
    try:
        subprocess.run(
            ["gh", "issue", "create", "--title", titulo, "--body", corpo, "--label", "promo"],
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        # Falhar o alerta não pode perder a coleta do dia.
        print(f"  aviso: não consegui abrir a issue ({e})", file=sys.stderr)


# --------------------------------------------------------------------------- principal


def main() -> int:
    cfg = json.loads((RAIZ / "config.json").read_text(encoding="utf-8"))
    saida = RAIZ / cfg["saida_dir"]
    saida.mkdir(parents=True, exist_ok=True)

    arq_hist = saida / "historico.json"
    historico = json.loads(arq_hist.read_text(encoding="utf-8")) if arq_hist.exists() else {}
    # Fica fora do histórico de propósito: é estado operacional do coletor, não dado
    # da tela, e a SPA não precisa baixar isso.
    arq_mortas = saida / "rotas_mortas.json"
    mortas = json.loads(arq_mortas.read_text(encoding="utf-8")) if arq_mortas.exists() else {}

    hoje = date.today().isoformat()
    # MAX_BUSCAS corta a varredura: serve para testar rápido e para encurtar o job se o
    # Actions estiver apertado, sem mexer no config. Conta COMBINAÇÕES, não requisições:
    # com o retry de página vazia, cada uma custa até `tentativas` requisições ao Google.
    restantes = int(os.environ.get("MAX_BUSCAS") or cfg.get("max_buscas_por_execucao", 150))
    pausa = cfg.get("pausa_segundos", 2)
    # Abaixo disso a escala não dá para sair do aeroporto, passar imigração e voltar sem
    # correr — então não vale sinalizar como oportunidade.
    escala_min = int(cfg.get("escala_min_horas", 8) * 60)
    # Países cuja conexão exige visto que eu não tenho. Não filtra a busca (o Google não
    # tem esse filtro); marca a oferta para a tela poder esconder.
    evitar_paises = set(cfg.get("evitar_paises", []))
    resultado, disparos = [], []

    for setup in cfg["setups"]:
        print(f"setup {setup['nome']}")
        origens = expandir(setup["origem"], cfg.get("max_cidades", 0))
        destinos = expandir(setup["destino"], cfg.get("max_cidades", 0))
        pares = datas(setup["meses"], setup["estadia_dias"], cfg.get("passo_dias", 2))
        ofertas = []
        top = setup.get("top_destinos", cfg.get("top_destinos", 5))

        achados = []  # (origem, destino, ida, volta, voo, url, veio_da_sonda)
        ja_visto = set()

        if pares and len(origens) * len(destinos) > top:
            # Data representativa: o meio do período pedido.
            par_sonda = pares[len(pares) // 2]
            destinos, sondadas, gastas = sondar(
                origens, destinos, par_sonda, setup.get("max_paradas"), top,
                restantes, pausa, mortas, hoje, historico,
            )
            restantes -= gastas
            for o, d, ida, volta, voo, url in sondadas:
                achados.append((o, d, ida, volta, voo, url, True))
                ja_visto.add((o, d, ida, volta))

        for o in origens:
            for d in destinos:
                for ida, volta in pares:
                    if (o, d, ida, volta) in ja_visto:  # a sonda já cotou este
                        continue
                    if restantes <= 0:
                        print("  teto de buscas atingido; o resto fica para amanhã")
                        break
                    restantes -= 1
                    try:
                        achado = consultar(o, d, ida, volta, setup.get("max_paradas"))
                    except Exception as e:  # rede, bloqueio, formato novo: não derruba o job
                        print(f"  {o}-{d} {ida}: falhou ({type(e).__name__})", file=sys.stderr)
                        achado = None
                    time.sleep(pausa)
                    if achado is not None:
                        achados.append((o, d, ida, volta, *achado, False))

        # Mediana ANTES de gravar a coleta de hoje: comparar o preço de hoje com uma
        # mediana que já inclui hoje mascara justamente a queda que se quer detectar.
        for o, d, ida, volta, voo, url, sonda in achados:
            mediana = mediana_rota(historico, f"{o}-{d}")
            bateu, motivo = disparou(voo.preco, mediana, setup.get("gatilho", {}))
            # A escala longa não custa busca nenhuma: já vem no mesmo rótulo. É o que
            # transforma uma conexão chata numa passada por Seul ou Doha.
            longa = voo.escala_longa(escala_min)
            paises, escalas_sem_pais = paises_de_escala(voo)
            # Conexão nos EUA exige visto mesmo sem sair do aeroporto: não existe área de
            # trânsito internacional lá, todo passageiro passa pela imigração. Para quem
            # não tem visto, um itinerário desses não é alternativa — é descarte.
            evitar = [p for p in paises if p in evitar_paises]
            oferta = {
                "origem": o, "destino": d, "ida": ida, "volta": volta,
                "preco": voo.preco, "cia": voo.cia, "paradas": voo.paradas,
                "duracao_min": voo.duracao_min, "url": url,
                "promo": bateu, "motivo": motivo, "mediana": mediana, "sonda": sonda,
                "escalas": voo.dict()["escalas"],
                "paises_escala": paises,
                "exige_visto": evitar,
                # Escala que nenhuma tabela reconheceu: a tela precisa dizer "não sei",
                # em vez de deixar passar como se estivesse liberada.
                "escalas_sem_pais": escalas_sem_pais,
                "escala_longa": (
                    {"duracao_min": longa[0], "aeroporto": longa[1], "cidade": longa[2]}
                    if longa else None
                ),
            }
            ofertas.append(oferta)
            if bateu:
                disparos.append({**oferta, "setup": setup["nome"]})

        # Stopover: só em cima do que a varredura JÁ provou bom. Testar todo hub × toda
        # data × todo nº de dias daria centenas de combinações a 2 buscas cada; partindo
        # das melhores ofertas, são algumas dezenas e a pergunta é a que interessa —
        # "esticar uma parada no caminho sai melhor que o voo que achei?".
        sv = setup.get("stopover")
        if sv and ofertas:
            hubs = expandir(sv["em"], cfg.get("max_cidades", 0))
            cache_perna1: dict = {}
            bases = sorted(ofertas, key=lambda x: x["preco"])[: sv.get("datas", 2)]
            print(f"  stopover: hubs {hubs} sobre {len(bases)} melhor(es) data(s)")

            for base in bases:
                for hub in hubs:
                    if hub in (base["origem"], base["destino"]):
                        continue
                    # As duas ordens possíveis, porque mudam a viagem e o preço:
                    #   (hub, destino) -> "Brasil → China, uns dias, depois o Japão"
                    #   (destino, hub) -> "Brasil → Japão, uns dias na Coreia, volta"
                    # O destino do setup aparece nas duas, então ele é sempre visitado.
                    ordens = [(hub, base["destino"]), (base["destino"], hub)]
                    for primeira, segunda in ordens:
                        for n in amostrar(sv["dias"]):
                            if restantes <= 1:
                                break
                            restantes -= 2  # as duas pernas
                            try:
                                rota = cotar_stopover(
                                    base["origem"], primeira, segunda, base["ida"],
                                    base["volta"], n, setup.get("max_paradas"),
                                    cache_perna1, pausa,
                                )
                            except Exception as e:
                                print(f"  stopover {primeira}-{segunda} {n}d: falhou "
                                      f"({type(e).__name__})", file=sys.stderr)
                                continue
                            if rota is None:
                                continue
                            bateu, motivo = disparou(
                                rota["preco"], base.get("mediana"), setup.get("gatilho", {})
                            )
                            ofertas.append({
                                "origem": base["origem"], "destino": segunda,
                                "ida": base["ida"], "volta": base["volta"],
                                "preco": rota["preco"], "cia": None,
                                "paradas": None, "duracao_min": None,
                                "url": rota["pernas"][0]["url"],
                                "promo": bateu, "motivo": motivo,
                                "mediana": base.get("mediana"), "sonda": False,
                                # Comparar com o voo que serviu de base é o que dá sentido
                                # ao número: "R$ 400 a mais, e você ganha 4 dias em Seul".
                                "stopover": {**rota, "base_preco": base["preco"],
                                             "dois_bilhetes": True},
                            })
                            if bateu:
                                disparos.append({**ofertas[-1], "setup": setup["nome"]})

        # Uma observação por rota por dia: a mais barata vista hoje.
        for chave, preco in minimo_por_rota(achados).items():
            serie = historico.setdefault(chave, [])
            serie[:] = [[dia, p] for dia, p in serie if dia != hoje]
            serie.append([hoje, preco])

        ofertas.sort(key=lambda x: x["preco"])
        resultado.append({
            "nome": setup["nome"],
            "origem": setup["origem"],
            "destino": setup["destino"],
            "gatilho": setup.get("gatilho", {}),
            "ofertas": ofertas,
        })

    historico = podar(historico, cfg.get("historico_dias", 180))
    arq_hist.write_text(json.dumps(historico, ensure_ascii=False), encoding="utf-8")
    arq_mortas.write_text(json.dumps(mortas, ensure_ascii=False), encoding="utf-8")
    (saida / "precos.json").write_text(
        json.dumps(
            {"gerado_em": datetime.now().astimezone().isoformat(), "setups": resultado},
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )

    total = sum(len(s["ofertas"]) for s in resultado)
    print(f"{total} ofertas, {len(disparos)} disparo(s), {len(historico)} rotas no histórico")
    avisar(disparos)
    return 0


if __name__ == "__main__":
    sys.exit(main())
