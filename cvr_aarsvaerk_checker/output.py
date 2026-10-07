"""Skriv resultater som CSV-filer, der kan åbnes direkte i dansk Excel.

Format: semikolon som separator, decimalkomma og UTF-8 med BOM (så æ/ø/å
vises korrekt). Tal afrundes KUN her, til visning – aldrig i beregningen.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable
from decimal import MAX_EMAX, MIN_EMIN, ROUND_HALF_UP, Decimal, localcontext
from pathlib import Path

from .analyse import MATCH, Resultat, formater_maaned

KOLONNER = [
    "cvr_nummer",
    "virksomhedsnavn",
    "seneste_registrerede_maaned",
    "periode_a_start",
    "periode_a_slut",
    "gennemsnit_aarsvaerk_periode_a",
    "periode_b_start",
    "periode_b_slut",
    "gennemsnit_aarsvaerk_periode_b",
    "absolut_aendring",
    "procent_aendring",
    "seneste_aarsvaerk",
    "seneste_aarsvaerk_periode",
    "status",
    "note",
]

_TO_DECIMALER = Decimal("0.01")


def formater_tal(vaerdi: Decimal | None) -> str:
    if vaerdi is None:
        return ""
    with localcontext() as ctx:
        ctx.prec = max(28, vaerdi.adjusted() + 4)  # plads til alle cifre før kommaet
        ctx.Emax, ctx.Emin = MAX_EMAX, MIN_EMIN
        afrundet = vaerdi.quantize(_TO_DECIMALER, rounding=ROUND_HALF_UP)
    if afrundet == 0:
        afrundet = abs(afrundet)  # undgå "-0,00"
    return f"{afrundet:.2f}".replace(".", ",")


def _maaned(indeks: int | None) -> str:
    return "" if indeks is None else formater_maaned(indeks)


def _sikker_tekst(tekst: str) -> str:
    """Forhindr at Excel tolker tekst fra inputfilen som en formel."""
    return "'" + tekst if tekst[:1] in ("=", "+", "-", "@", "\t", "\r") else tekst


def som_raekke(r: Resultat) -> list[str]:
    return [
        _sikker_tekst(r.cvr_nummer),
        _sikker_tekst(r.virksomhedsnavn),
        _maaned(r.seneste_registrerede_maaned),
        _maaned(r.periode_a_start),
        _maaned(r.periode_a_slut),
        formater_tal(r.gennemsnit_a),
        _maaned(r.periode_b_start),
        _maaned(r.periode_b_slut),
        formater_tal(r.gennemsnit_b),
        formater_tal(r.absolut_aendring),
        formater_tal(r.procent_aendring),
        formater_tal(r.seneste_aarsvaerk),
        _maaned(r.seneste_aarsvaerk_periode),
        r.status,
        _sikker_tekst(r.note),
    ]


def skriv_csv(sti: Path, resultater: Iterable[Resultat]) -> None:
    sti.parent.mkdir(parents=True, exist_ok=True)
    with sti.open("w", encoding="utf-8-sig", newline="") as f:
        skriver = csv.writer(f, delimiter=";")
        skriver.writerow(KOLONNER)
        for r in resultater:
            skriver.writerow(som_raekke(r))


def skriv_resultater(mappe: Path, resultater: list[Resultat]) -> tuple[Path, Path]:
    """Skriv matches.csv (kun MATCH, største stigning først) og alle_resultater.csv."""
    matches = sorted(
        (r for r in resultater if r.status == MATCH),
        key=lambda r: r.absolut_aendring or Decimal(0),
        reverse=True,
    )
    matches_sti = mappe / "matches.csv"
    alle_sti = mappe / "alle_resultater.csv"
    skriv_csv(matches_sti, matches)
    skriv_csv(alle_sti, resultater)
    return matches_sti, alle_sti
