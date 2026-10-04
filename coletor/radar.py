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
from pathlib import Path

from extrator import mais_barato
from extrator import extrair_voos
from fast_flights import FlightQuery, Passengers, create_query, fetch_flights_html

RAIZ = Path(__file__).resolve().parent.parent
CACHE = Path(__file__).resolve().parent / "cache"

# Duas tabelas públicas e sem token, cada uma pelo que a outra não tem: a Travelpayouts dá
# o código de CIDADE (buscar `TYO` cobre Haneda e Narita de uma vez, `SAO` cobre
# GRU+CGH+VCP) e a OurAirports (CC0) dá o PORTE real do aeroporto, que é o que separa
# Fukuoka de Asahikawa. Só com o nome ("International") a escolha saía errada.
AEROPORTOS_URL = "https://api.travelpayouts.com/data/en/airports.json"
PORTE_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"

_PORTE = {"large_airport": 2, "medium_airport": 1}


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


def expandir(alvo: str | list[str], max_cidades: int) -> list[str]:
    """Resolve o guarda-chuva em códigos que o Google Flights aceita.

    - lista -> usada como está;
    - 3 letras (`SAO`, `GRU`, `TYO`) -> usada como está. Código de cidade já é guarda-chuva
      nativo e vale uma busca só;
    - 2 letras (`JP`) -> país: expande para as cidades mais relevantes dele. O Google
      **não** aceita país (`SAO->JP` devolveu zero resultados em 2026-10-04), e é por isso
      que esta função existe — nenhum alerta pronto cobre "o Japão inteiro".
    """
    if isinstance(alvo, list):
        return alvo
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


def datas(meses: list[str], estadias: list[int], passo: int) -> list[tuple[str, str]]:
    """Pares (ida, volta) dentro dos meses pedidos.

    Varrer mês inteiro × toda estadia explode (31 × 11 = 341 buscas por rota), então
    amostra: ida a cada `passo` dias e só os extremos e o meio da faixa de estadia.
    """
    estadias = sorted({min(estadias), (min(estadias) + max(estadias)) // 2, max(estadias)})
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
        voo = mais_barato(extrair_voos(fetch_flights_html(q)))
        if voo is not None:
            return voo, q.url()
        if tentativa + 1 < tentativas:
            time.sleep(pausa * (tentativa + 2))  # a segunda espera é maior que a primeira
    return None


# --------------------------------------------------------------------------- gatilho


def sondar(origens, destinos, par, max_paradas, top, orcamento, pausa, mortas, hoje):
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
                achado = consultar(o, d, ida, volta, max_paradas)
            except Exception as e:
                print(f"  sonda {o}-{d}: falhou ({type(e).__name__})", file=sys.stderr)
                continue
            finally:
                time.sleep(pausa)
            marcar(mortas, f"{o}-{d}", achado is not None, hoje)
            if achado is None:
                continue  # Google não cota essa cidade a partir daqui: fora do radar
            voo, url = achado
            precos[d] = min(precos.get(d, voo.preco), voo.preco)
            ofertas.append((o, d, ida, volta, voo, url))

    escolhidos = sorted(precos, key=lambda d: precos[d])[:top]
    print(f"  sonda: {len(precos)}/{len(destinos)} cidades com voo, "
          f"aprofundando {[(d, precos[d]) for d in escolhidos]}")
    return escolhidos, ofertas, gastas


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


def marcar(mortas: dict, chave: str, achou: bool, hoje: str) -> dict:
    """Conta vazios consecutivos; achar preço ressuscita a rota na hora."""
    if achou:
        mortas.pop(chave, None)
        return mortas
    reg = mortas.setdefault(chave, {"vazios": 0})
    reg["vazios"] += 1
    if reg["vazios"] >= VAZIOS_PARA_MORRER:
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
    if not disparos or not os.environ.get("GITHUB_ACTIONS"):
        for d in disparos:
            print(f"  ALERTA {d['setup']}: R$ {d['preco']} {d['origem']}->{d['destino']} "
                  f"{d['ida']} a {d['volta']} ({d['motivo']})")
        return

    titulo = f"Promo: {len(disparos)} oferta(s) abaixo do gatilho — {date.today().isoformat()}"
    corpo = "\n".join(
        f"- **R$ {d['preco']}** · {d['setup']} · {d['origem']}→{d['destino']} · "
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
                restantes, pausa, mortas, hoje,
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
            oferta = {
                "origem": o, "destino": d, "ida": ida, "volta": volta,
                "preco": voo.preco, "cia": voo.cia, "paradas": voo.paradas,
                "duracao_min": voo.duracao_min, "url": url,
                "promo": bateu, "motivo": motivo, "mediana": mediana, "sonda": sonda,
            }
            ofertas.append(oferta)
            if bateu:
                disparos.append({**oferta, "setup": setup["nome"]})

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
