"""Extrai voos do HTML do Google Flights.

Por que não usar o parser do `fast-flights` (2090 estrelas, MIT): ele ancora em classes
CSS (`kw4HXCc5QE=`), que o Google reescreve a cada deploy — em 2026-10-04 a versão 3.1.0
devolveu 0 voos para JFK->LAX com o HTML chegando intacto. Ancoramos no `aria-label`, que
é contrato de acessibilidade: mudar quebra leitor de tela, então muda raramente.

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

    def dict(self) -> dict:
        return asdict(self)


def _int(m: re.Match | None, grupo: int = 1) -> int | None:
    return int(m.group(grupo)) if m and m.group(grupo) else None


def _hora(s: str) -> str:
    return s.replace(" ", " ").strip()


def extrair_voos(html: str) -> list[Voo]:
    """Voos do HTML, deduplicados: o Google repete o mesmo card em seções
    diferentes ("melhores voos" e a lista completa)."""
    voos: list[Voo] = []
    vistos: set[Voo] = set()
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
        )
        if voo not in vistos:
            vistos.add(voo)
            voos.append(voo)
    return voos


def mais_barato(voos: list[Voo]) -> Voo | None:
    return min(voos, key=lambda v: v.preco, default=None)
