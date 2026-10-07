"""Virksomhedsnavne til resultatfilerne.

Svaret fra endpointet for ansatte og årsværk indeholder kun cvr_nummer og
historikken – ikke navnet. Navnet hentes derfor fra cvr.dev's endpoint med
rå CVR-data (/api/cvr/virksomhed), som tager op til 10 CVR-numre pr. kald.
Kun selve navnet gemmes lokalt, så det ikke hentes igen. Navnene påvirker
ikke analysen eller status.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from .analyse import FEJL, Resultat
from .api import CvrDevKlient, FatalApiFejl, OpslagFejl, RaaSvarCache

NAVNE_PR_KALD = 10
NAVNE_CACHE_DAGE = 90  # navne ændrer sig sjældent
MANGLER_NOTE = "virksomhedsnavn mangler"


class UgyldigtNavneSvar(Exception):
    """Svaret fra virksomheds-endpointet har ikke det forventede format."""


def _navn(virksomhed: dict[str, Any]) -> str:
    metadata = virksomhed.get("virksomhedMetadata") or {}
    navn = (metadata.get("nyesteNavn") or {}).get("navn")
    if not navn:
        navne = [n for n in virksomhed.get("navne") or [] if isinstance(n, dict) and n.get("navn")]
        navn = navne[-1]["navn"] if navne else ""
    return str(navn).strip()


def parse_navne(raa_svar: str) -> dict[str, str]:
    """Råt svar fra /api/cvr/virksomhed -> {cvr_nummer: navn}."""
    try:
        data = json.loads(raa_svar)
    except ValueError as e:
        raise UgyldigtNavneSvar(f"svaret er ikke gyldig JSON ({e})") from None
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        raise UgyldigtNavneSvar("svaret er ikke en liste af virksomheder")
    navne: dict[str, str] = {}
    for virksomhed in data:
        if isinstance(virksomhed, dict) and virksomhed.get("cvrNummer") is not None:
            navn = _navn(virksomhed)
            if navn:
                navne[str(virksomhed["cvrNummer"])] = navn
    return navne


def _fra_cache(cache: RaaSvarCache, cvr: str, max_alder_dage: float | None) -> str | None:
    raa = cache.hent(cvr, max_alder_dage)
    if raa is None:
        return None
    try:
        navn = json.loads(raa).get("navn")
    except (ValueError, AttributeError):
        return None
    return navn if isinstance(navn, str) and navn else None


def tilfoej_navne(
    resultater: list[Resultat],
    *,
    klient: CvrDevKlient,
    cache: RaaSvarCache,
    kun_cache: bool = False,
    opdater: bool = False,
    udskriv: Callable[[str], None] = print,
) -> list[Resultat]:
    """Sæt virksomhedsnavn på alle resultater, der ikke er FEJL.

    Navne findes først i den lokale cache; resten hentes i kald med op til
    10 CVR-numre. Kan et navn ikke findes, får rækken en note – status og
    beregninger ændres aldrig.
    """
    behov = list(dict.fromkeys(r.cvr_nummer for r in resultater if r.status != FEJL))
    navne: dict[str, str] = {}
    mangler: list[str] = []
    for cvr in behov:
        navn = None if opdater else _fra_cache(cache, cvr, None if kun_cache else NAVNE_CACHE_DAGE)
        if navn:
            navne[cvr] = navn
        else:
            mangler.append(cvr)

    if mangler and not kun_cache:
        udskriv(f"Henter virksomhedsnavne for {len(mangler)} CVR-numre ({NAVNE_PR_KALD} pr. API-kald) …")
        for start in range(0, len(mangler), NAVNE_PR_KALD):
            parti = mangler[start : start + NAVNE_PR_KALD]
            try:
                fundne = parse_navne(klient.hent_virksomheder(parti))
            except FatalApiFejl as e:
                udskriv(f"Navneopslag stoppet: {e}")
                break
            except (OpslagFejl, UgyldigtNavneSvar) as e:
                udskriv(f"Navneopslag fejlede for {', '.join(parti)}: {e}")
                continue
            for cvr in parti:
                if cvr in fundne:
                    navne[cvr] = fundne[cvr]
                    try:
                        cache.gem(cvr, json.dumps({"navn": fundne[cvr]}, ensure_ascii=False))
                    except OSError:
                        pass  # navnet bruges stadig i denne kørsel

    def med_navn(r: Resultat) -> Resultat:
        if r.status == FEJL:
            return r
        navn = navne.get(r.cvr_nummer, "")
        if navn:
            return replace(r, virksomhedsnavn=navn)
        return replace(r, note=f"{r.note}; {MANGLER_NOTE}" if r.note else MANGLER_NOTE)

    return [med_navn(r) for r in resultater]
