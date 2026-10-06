"""Indlæsning af CVR-numre fra en tekst- eller CSV-fil.

Regler:
* Tomme linjer og linjer der starter med '#' springes over.
* Er første linje en overskrift med en kolonne, der indeholder "cvr"
  (fx "cvr", "CVR-nummer", "cvr_nummer"), bruges den kolonne.
  Ellers bruges første kolonne. Kolonner adskilles af ; , eller tab.
* Mellemrum og et eventuelt "DK"-præfiks fjernes (fx "DK 1234 5678").
* Et gyldigt CVR-nummer er præcis 8 cifre og starter ikke med 0.
* Dubletter fjernes; første forekomst bevares.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_SEPARATOR_RE = re.compile(r"[;,\t]")
_CVR_RE = re.compile(r"[1-9]\d{7}")


@dataclass
class Indlaesning:
    gyldige: list[str] = field(default_factory=list)
    ugyldige: list[str] = field(default_factory=list)  # rå værdier, til FEJL-rækker
    antal_dubletter: int = 0


def normaliser(vaerdi: str) -> str:
    v = vaerdi.strip().strip('"').strip("'")
    v = re.sub(r"\s+", "", v)
    if v[:2].upper() == "DK":
        v = v[2:]
    return v


def er_gyldigt_cvr(cvr: str) -> bool:
    return _CVR_RE.fullmatch(cvr) is not None


def _laes_tekst(sti: Path) -> str:
    data = sti.read_bytes()
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252")  # CSV gemt fra Excel på dansk Windows


def laes_cvr_numre(sti: Path) -> Indlaesning:
    linjer = [linje for linje in _laes_tekst(sti).splitlines() if linje.strip() and not linje.lstrip().startswith("#")]
    kolonne = 0
    if linjer:
        felter = [f.strip().strip('"').lower() for f in _SEPARATOR_RE.split(linjer[0])]
        cvr_kolonner = [i for i, f in enumerate(felter) if "cvr" in f]
        if cvr_kolonner:
            kolonne = cvr_kolonner[0]
            linjer = linjer[1:]

    resultat = Indlaesning()
    set_foer: set[str] = set()
    for linje in linjer:
        felter = _SEPARATOR_RE.split(linje)
        raa = felter[kolonne] if kolonne < len(felter) else ""
        cvr = normaliser(raa)
        noegle = cvr or raa.strip()
        if noegle in set_foer:
            resultat.antal_dubletter += 1
            continue
        set_foer.add(noegle)
        if er_gyldigt_cvr(cvr):
            resultat.gyldige.append(cvr)
        else:
            resultat.ugyldige.append(raa.strip())
    return resultat
