"""Verificação mínima, sem rede: `python coletor/test_radar.py`.

Os rótulos abaixo são reais, copiados do HTML do Google Flights em 2026-10-04. Se o
Google mudar o formato, é aqui que estoura primeiro — e o extrator inteiro depende disso.
"""

from datetime import date, timedelta

from extrator import extrair_voos, mais_barato
from radar import (
    datas,
    disparou,
    esta_morta,
    expandir,
    marcar,
    mediana_rota,
    minimo_por_rota,
    podar,
)

SO_IDA = (
    "From 1529 Brazilian reals. Nonstop flight with JetBlue. Leaves John F. Kennedy "
    "International Airport at 2:00 PM on Friday, November 20 and arrives at Los Angeles "
    "International Airport at 5:18 PM on Friday, November 20. Total duration 6 hr 18 min. "
    " 1 carry-on bag included. 0 checked bags included.  Select flight"
)
IDA_VOLTA = (
    "From 7927 Brazilian reals round trip total. 1 stop flight with LATAM and JAL. "
    "Operated by Latam Airlines Brasil. Leaves São Paulo/Guarulhos–Governor André Franco "
    "Montoro International Airport at 6:20 PM on Thursday, December 10 and arrives at "
    "Haneda Airport at 2:50 PM on Saturday, December 12. Total duration 32 hr 30 min.  "
    "Layover (1 of 1) is a 7 hr 5 min layover at Tom Jobim International Airport in Rio de "
    "Janeiro.  Select flight"
)


def html(*rotulos: str) -> str:
    return "".join(f'<li aria-label="{r}"><span>R$</span></li>' for r in rotulos)


def test_extrator():
    (v,) = extrair_voos(html(SO_IDA))
    assert v.preco == 1529, v.preco
    assert v.moeda == "Brazilian reals", v.moeda
    assert v.ida_volta is False
    assert v.cia == "JetBlue", v.cia
    assert v.paradas == 0, v.paradas
    assert v.duracao_min == 6 * 60 + 18, v.duracao_min
    assert v.saida == "2:00 PM", repr(v.saida)  # espaço estreito normalizado
    assert v.destino == "Los Angeles International Airport", v.destino
    assert (v.bagagem_mao, v.bagagem_despachada) == (1, 0)

    (r,) = extrair_voos(html(IDA_VOLTA))
    assert r.preco == 7927, r.preco
    assert r.moeda == "Brazilian reals", r.moeda  # e não "reals round trip total"
    assert r.ida_volta is True
    assert r.paradas == 1, r.paradas
    assert r.duracao_min == 32 * 60 + 30, r.duracao_min
    assert r.bagagem_despachada is None  # rota internacional não informa: None, não 0

    # O Google repete o mesmo card em "melhores voos" e na lista completa.
    assert len(extrair_voos(html(SO_IDA, SO_IDA, IDA_VOLTA))) == 2
    # Rótulo que não é resultado de voo nunca entra.
    assert extrair_voos(html("Track prices from New York to Los Angeles departing 2026-11-20")) == []
    assert mais_barato(extrair_voos(html(IDA_VOLTA, SO_IDA))).preco == 1529
    assert mais_barato([]) is None


def test_gatilho():
    # Teto: dispara no limite, não dispara um real acima.
    assert disparou(4500, None, {"teto_brl": 4500})[0] is True
    assert disparou(4501, None, {"teto_brl": 4500})[0] is False

    # Mediana: 25% abaixo de 8000 = 6000.
    assert disparou(6000, 8000, {"pct_abaixo_mediana": 25})[0] is True
    assert disparou(6001, 8000, {"pct_abaixo_mediana": 25})[0] is False

    # Sem histórico, o critério de mediana não pode disparar sozinho.
    assert disparou(10, None, {"pct_abaixo_mediana": 90})[0] is False
    # Gatilho vazio nunca dispara (config incompleto não vira alarme falso).
    assert disparou(1, 9999, {})[0] is False
    # Qualquer um dos dois basta.
    ok, motivo = disparou(5000, 8000, {"teto_brl": 100, "pct_abaixo_mediana": 25})
    assert ok and "mediana" in motivo, motivo


def test_mediana_e_poda():
    hist = {"SAO-TYO": [["2026-10-01", 8000], ["2026-10-02", 7000], ["2026-10-03", 9000]]}
    assert mediana_rota(hist, "SAO-TYO") == 8000
    # Série curta não vira mediana: 2 pontos não descrevem o normal da rota.
    assert mediana_rota({"X": [["2026-10-01", 1]]}, "X") is None
    assert mediana_rota(hist, "NAO-EXISTE") is None

    velho = (date.today() - timedelta(days=200)).isoformat()
    novo = (date.today() - timedelta(days=10)).isoformat()
    podado = podar({"R": [[velho, 1], [novo, 2]]}, 180)
    assert podado["R"] == [[novo, 2]], podado


def test_minimo_por_rota():
    (voo,) = extrair_voos(html(IDA_VOLTA))      # 7927
    (barato,) = extrair_voos(html(SO_IDA))      # 1529
    achados = [
        ("SAO", "TYO", "2027-01-05", "2027-01-15", voo, "u", False),
        ("SAO", "TYO", "2027-01-08", "2027-01-18", barato, "u", False),
        ("SAO", "OSA", "2027-01-05", "2027-01-15", voo, "u", True),
    ]
    # Uma linha por rota no histórico, com o MENOR preço visto hoje nela.
    assert minimo_por_rota(achados) == {"SAO-TYO": 1529, "SAO-OSA": 7927}
    assert minimo_por_rota([]) == {}


def test_rotas_mortas():
    hoje = date.today().isoformat()
    mortas = {}

    # Dois vazios não matam: pode ter sido a página que não veio.
    for _ in range(2):
        marcar(mortas, "SAO-AKJ", False, hoje)
    assert esta_morta(mortas, "SAO-AKJ", hoje) is False
    assert mortas["SAO-AKJ"]["vazios"] == 2

    marcar(mortas, "SAO-AKJ", False, hoje)  # terceiro: descansa 30 dias
    assert esta_morta(mortas, "SAO-AKJ", hoje) is True
    depois = (date.today() + timedelta(days=31)).isoformat()
    assert esta_morta(mortas, "SAO-AKJ", depois) is False, "o descanso tem que expirar"

    # Achar preço ressuscita na hora, sem esperar o prazo.
    marcar(mortas, "SAO-AKJ", True, hoje)
    assert "SAO-AKJ" not in mortas
    assert esta_morta(mortas, "SAO-AKJ", hoje) is False
    # Rota nunca vista nunca está morta.
    assert esta_morta({}, "SAO-TYO", hoje) is False


def test_expansao_e_datas():
    assert expandir(["GRU", "VCP"], 8) == ["GRU", "VCP"]
    assert expandir("SAO", 8) == ["SAO"]  # código de cidade já é guarda-chuva nativo

    mes = (date.today().replace(day=1) + timedelta(days=40)).strftime("%Y-%m")
    pares = datas([mes], [10, 20], passo=3)
    assert pares, "mês futuro tem que gerar pares"
    assert all(i < v for i, v in pares), "volta sempre depois da ida"
    assert all(i > date.today().isoformat() for i, _ in pares), "não cotar passado"
    # [10, 20] vira [10, 15, 20]: extremos e meio.
    assert len({(date.fromisoformat(v) - date.fromisoformat(i)).days for i, v in pares}) == 3

    # Mês já passado não gera busca nenhuma.
    assert datas(["2020-01"], [10], passo=3) == []


if __name__ == "__main__":
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_"):
            fn()
            print(f"ok {nome}")
    print("tudo verde")
