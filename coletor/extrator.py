"""Extrai voos do HTML do Google Flights.

Por que não usar o parser do `fast-flights` (2090 estrelas, MIT): ele lê o JSON embutido no
`<script class="ds:1">` da página. Esse script **continua existindo** no HTML, mas o parser
não extrai nada dele — devolveu 0 voos em 4 tentativas (SAO->TYO, 2026-10-04) usando o
`main` do upstream, já com a correção do `tfu`, contra 96 voos do extrator deste arquivo no
MESMO HTML. Ou seja: a estrutura do JSON mudou por baixo.

Aqui ancoramos no `aria-label`, que é contrato de acessibilidade: mudar quebra leitor de
tela, então muda muito mais devagar que um blob JSON interno.

Do `fast-flights` reaproveitamos só o que funciona e é chato de refazer: a codificação
protobuf+base64 da URL (`create_query`) e o fetch (`fetch_flights_html`).

Dois formatos de rótulo, ambos verificados em 2026-10-04:

    só ida    From 1529 Brazilian reals. Nonstop flight with JetBlue. Leaves John F.
              Kennedy International Airport at 2:00 PM on Friday, November 20 and arrives
              at Los Angeles International Airport at 5:18 PM on Friday, November 20.
              Total duration 6 hr 18 min.  1 carry-on bag included. 0 checked bags
              included.  Select flight

    ida/volta From 7927 Brazilian reals round trip total. 1 stop flight with LATAM and
              JAL. Operated by Latam Airlines Brasil. Leaves ... Total duration 32 hr
              30 min.  Layover (1 of 1) is a 7 hr 5 min layover at ...

O "round trip total" importa: o preço de ida-volta **não** é a soma de duas buscas de só
ida (GRU->TYO 2026-12-10 deu 4643 só ida contra 7927 ida-volta). O radar sempre consulta
ida-volta; a informação de bagagem só aparece em algumas rotas (ausente nas internacionais
testadas), então vem como None em vez de 0.
"""

from __future__ import annotations

import html as _html
import re
from dataclasses import asdict, dataclass

# Só os rótulos de resultado começam com "From <n> <moeda>"; o resto da página
# (botões, "Track prices", tooltips) não casa. O teto é folgado de propósito: o rótulo
# de ida-volta descreve as escalas e passa de 600 caracteres.
_ROTULO = re.compile(r'aria-label="(From \d[^"]{40,2500})"')

_PRECO = re.compile(r"^From ([\d,]+) ((?:[A-Za-z.]+ ?){1,3}?)(?: round trip total)?\.")
_PARADAS = re.compile(r"\b(Nonstop|(\d+) stops?)\b", re.I)
_CIA = re.compile(r"flight with ([^.]+?)\.")
_TRECHO = re.compile(
    r"Leaves (?P<origem>.+?) at (?P<saida>\d{1,2}:\d{2}\s*[AP]M) on .+?"
    r"and arrives at (?P<destino>.+?) at (?P<chegada>\d{1,2}:\d{2}\s*[AP]M) on",
    re.S,
)
_DURACAO = re.compile(r"Total duration (?:(\d+) hr)?\s*(?:(\d+) min)?")
_BAGAGEM_MAO = re.compile(r"(\d+) carry-on bag")
_BAGAGEM_DESPACHADA = re.compile(r"(\d+) checked bag")

# "Layover (1 of 2) is a 1 hr 45 min layover at Salvador International Airport in Salvador."
# Fatiado em blocos primeiro porque o nome do aeroporto contém ponto ("John F. Kennedy
# International Airport") — regex ancorada em "." recortaria no lugar errado.
_BLOCO_ESCALA = re.compile(
    r"Layover \(\d+ of \d+\) is an? (.+?)(?=Layover \(|Select flight|$)", re.S
)
_ESCALA = re.compile(r"(?:(\d+) hr\s*)?(?:(\d+) min\s*)?layover at (.+)", re.S)


@dataclass(frozen=True)
class Voo:
    preco: int
    moeda: str
    ida_volta: bool
    cia: str | None
    paradas: int
    origem: str | None
    destino: str | None
    saida: str | None
    chegada: str | None
    duracao_min: int | None
    bagagem_mao: int | None
    bagagem_despachada: int | None
    escalas: tuple[tuple[int, str, str | None], ...] = ()

    def dict(self) -> dict:
        d = asdict(self)
        d["escalas"] = [
            {"duracao_min": m, "aeroporto": a, "cidade": c} for m, a, c in self.escalas
        ]
        return d

    def escala_longa(self, minimo_min: int) -> tuple[int, str, str | None] | None:
        """A escala mais longa, se der para sair do aeroporto. É isso que transforma uma
        conexão chata em uma passada por Seul ou Doha."""
        return max(
            (e for e in self.escalas if e[0] >= minimo_min), key=lambda e: e[0], default=None
        )


def _int(m: re.Match | None, grupo: int = 1) -> int | None:
    return int(m.group(grupo)) if m and m.group(grupo) else None


def _hora(s: str) -> str:
    return s.replace(" ", " ").strip()


def _escalas(rotulo: str) -> tuple[tuple[int, str, str | None], ...]:
    """As escalas do voo: (minutos, aeroporto, cidade).

    Vem de graça no mesmo rótulo — é o que permite responder "essa escala dá para sair do
    aeroporto e dar uma volta?" sem nenhuma busca extra. Tupla, não lista, porque `Voo` é
    congelado e entra num `set` na deduplicação.
    """
    escalas = []
    for bloco in _BLOCO_ESCALA.findall(rotulo):
        m = _ESCALA.match(bloco.strip())
        if not m:
            continue
        minutos = int(m.group(1) or 0) * 60 + int(m.group(2) or 0)
        local = m.group(3).strip().rstrip(".").strip()
        # O texto termina em "<aeroporto> in <cidade>" e o nome do aeroporto tem pontos
        # ("John F. Kennedy"), então o separador é o ÚLTIMO " in ".
        aeroporto, _, cidade = local.rpartition(" in ")
        escalas.append((minutos, (aeroporto or local).strip(), cidade.strip() or None))
    return tuple(escalas)


def extrair_voos(html: str) -> list[Voo]:
    """Voos do HTML, deduplicados: o Google repete o mesmo card em seções
    diferentes ("melhores voos" e a lista completa)."""
    voos: list[Voo] = []
    vistos: set[Voo] = set()
    # O atributo vem com entidades HTML: "Chicago O&#39;Hare International Airport".
    # Sem desescapar, o nome não casa com nenhuma tabela de aeroporto — e aeroporto não
    # identificado vira escala sem país, que é justamente a que decide se precisa visto.
    html = _html.unescape(html)
    for rotulo in _ROTULO.findall(html):
        preco = _PRECO.match(rotulo)
        if not preco:  # rótulo com preço em formato inesperado: ignora em vez de mentir
            continue

        paradas_m = _PARADAS.search(rotulo)
        paradas = 0
        if paradas_m and paradas_m.group(2):
            paradas = int(paradas_m.group(2))

        trecho = _TRECHO.search(rotulo)
        dur = _DURACAO.search(rotulo)
        duracao = None
        if dur and (dur.group(1) or dur.group(2)):
            duracao = int(dur.group(1) or 0) * 60 + int(dur.group(2) or 0)

        cia = _CIA.search(rotulo)
        voo = Voo(
            preco=int(preco.group(1).replace(",", "")),
            moeda=preco.group(2).strip(),
            ida_volta="round trip total" in rotulo,
            cia=cia.group(1).strip() if cia else None,
            paradas=paradas,
            origem=trecho.group("origem").strip() if trecho else None,
            destino=trecho.group("destino").strip() if trecho else None,
            # O Google usa espaço estreito (U+202F) antes do AM/PM.
            saida=_hora(trecho.group("saida")) if trecho else None,
            chegada=_hora(trecho.group("chegada")) if trecho else None,
            duracao_min=duracao,
            bagagem_mao=_int(_BAGAGEM_MAO.search(rotulo)),
            bagagem_despachada=_int(_BAGAGEM_DESPACHADA.search(rotulo)),
            escalas=_escalas(rotulo),
        )
        if voo not in vistos:
            vistos.add(voo)
            voos.append(voo)
    return voos


def mais_barato(voos: list[Voo]) -> Voo | None:
    return min(voos, key=lambda v: v.preco, default=None)
