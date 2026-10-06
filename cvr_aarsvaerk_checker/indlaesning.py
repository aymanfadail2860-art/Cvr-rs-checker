"""Indlæsning af CVR-numre fra en tekst- eller CSV-fil.

Regler:
* Tomme linjer og linjer der starter med '#' springes over.
* Filens separator bestemmes ud fra første linje: ';' hvis den findes,
  ellers tab, ellers ','. Felter i anførselstegn håndteres korrekt.
  Har første linje ingen separator, er hver linje ét CVR-nummer.
* Er første linje en overskrift med en kolonne, der indeholder "cvr"
  (fx "cvr", "CVR-nummer", "cvr_nummer"), bruges den kolonne.
  Ellers bruges første kolonne.
* Mellemrum, "DK"-præfiks (fx "DK-1234 5678"), punktummer som
  tusindtalsseparator ("12.345.678") og Excels ".0" fjernes.
* Et gyldigt CVR-nummer er præcis 8 cifre og starter ikke med 0.
* Rækker med en tom CVR-celle springes over. Dubletter fjernes; første
  forekomst bevares.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

_CVR_RE = re.compile(r"[1-9]\d{7}")


@dataclass
class Indlaesning:
    gyldige: list[str] = field(default_factory=list)
    ugyldige: list[str] = field(default_factory=list)  # rå værdier, til FEJL-rækker
    antal_dubletter: int = 0
    antal_tomme: int = 0


def normaliser(vaerdi: str) -> str:
    v = re.sub(r"\s+", "", vaerdi.strip().strip('"').strip("'"))
    v = re.sub(r"^DK[-:.]?", "", v, flags=re.IGNORECASE)
    v = re.sub(r"^(\d+)\.0+$", r"\1", v)  # 12345678.0 fra Excel
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", v):  # 12.345.678
        v = v.replace(".", "")
    return v


def er_gyldigt_cvr(cvr: str) -> bool:
    return _CVR_RE.fullmatch(cvr) is not None


def _laes_tekst(sti: Path) -> str:
    data = sti.read_bytes()
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")  # Excel "Unicode-tekst"
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Ældre Excel/Windows/Mac-tegnsæt. Kun cifrene er vigtige, så ukendte
        # bogstaver må gerne blive til erstatningstegn.
        return data.decode("cp1252", errors="replace")


def laes_cvr_numre(sti: Path) -> Indlaesning:
    linjer = [linje for linje in _laes_tekst(sti).splitlines() if linje.strip() and not linje.lstrip().startswith("#")]
    resultat = Indlaesning()
    if not linjer:
        return resultat

    separator = next((t for t in ";\t," if t in linjer[0]), None)
    if separator is None:  # én kolonne: hele linjen er værdien
        raekker = [[linje] for linje in linjer]
    else:
        raekker = list(csv.reader(linjer, delimiter=separator))

    kolonne = 0
    overskrift = [f.strip().lower() for f in raekker[0]]
    cvr_kolonner = [i for i, f in enumerate(overskrift) if "cvr" in f]
    if cvr_kolonner:
        kolonne = cvr_kolonner[0]
        raekker = raekker[1:]

    set_foer: set[str] = set()
    for raekke in raekker:
        raa = raekke[kolonne].strip() if kolonne < len(raekke) else ""
        cvr = normaliser(raa)
        if not cvr:
            resultat.antal_tomme += 1
            continue
        if cvr in set_foer:
            resultat.antal_dubletter += 1
            continue
        set_foer.add(cvr)
        if er_gyldigt_cvr(cvr):
            resultat.gyldige.append(cvr)
        else:
            resultat.ugyldige.append(raa)
    return resultat
