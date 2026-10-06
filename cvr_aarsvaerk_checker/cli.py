"""Kommandolinje: python -m cvr_aarsvaerk_checker <inputfil> [valg]"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from .analyse import FEJL, IKKE_MATCH, MATCH, UTILSTRAEKKELIGE_DATA, Resultat, analyser_raa_svar, fejl_resultat
from .api import (
    MILJOEVARIABEL,
    CvrDevKlient,
    FatalApiFejl,
    GenforsoegOpbrugt,
    OpslagFejl,
    RaaSvarCache,
    hent_api_noegle,
)
from .indlaesning import laes_cvr_numre
from .output import skriv_resultater

# Stop kørslen hvis så mange opslag i træk fejler efter alle genforsøg,
# så vi ikke bruger timer på et API, der er nede.
MAX_FEJL_I_TRAEK = 5


def koer(
    cvr_numre: list[str],
    *,
    klient: CvrDevKlient,
    cache: RaaSvarCache,
    offline: bool = False,
    opdater: bool = False,
    cache_dage: float | None = 7,
    udskriv: Callable[[str], None] = print,
) -> tuple[list[Resultat], str | None]:
    """Behandl alle CVR-numre. Returnerer (resultater, årsag hvis kørslen blev stoppet)."""
    resultater: list[Resultat] = []
    noegle_testet = False
    fejl_i_traek = 0
    stop_aarsag: str | None = None
    antal = len(cvr_numre)

    for i, cvr in enumerate(cvr_numre, start=1):
        raa: str | None = None
        kilde = "gemt"
        resultat: Resultat | None = None
        try:
            if not opdater:
                raa = cache.hent(cvr, None if offline else cache_dage)
            if raa is None:
                if offline:
                    resultat = fejl_resultat(cvr, "intet gemt råsvar (offline-tilstand)")
                else:
                    if not noegle_testet:
                        klient.test_noegle()  # gratis kald; stopper tidligt ved forkert nøgle
                        noegle_testet = True
                    kilde = "hentet"
                    raa = klient.hent_ansatte(cvr)
                    fejl_i_traek = 0
            if raa is not None:
                resultat = analyser_raa_svar(cvr, raa)
                if kilde == "hentet" and resultat.status != FEJL:
                    cache.gem(cvr, raa)  # gem kun gyldige svar
        except FatalApiFejl as e:
            stop_aarsag = str(e)
        except GenforsoegOpbrugt as e:
            resultat = fejl_resultat(cvr, str(e))
            fejl_i_traek += 1
            if fejl_i_traek >= MAX_FEJL_I_TRAEK:
                stop_aarsag = f"{fejl_i_traek} opslag i træk fejlede efter genforsøg ({e})"
        except OpslagFejl as e:
            resultat = fejl_resultat(cvr, str(e))
        except Exception as e:  # anden teknisk fejl må ikke vælte hele kørslen
            resultat = fejl_resultat(cvr, f"teknisk fejl: {type(e).__name__}: {e}")

        if resultat is not None:
            resultater.append(resultat)
            udskriv(f"[{i:>{len(str(antal))}}/{antal}] {cvr}  {kilde:<6}  {resultat.status}")
        if stop_aarsag:
            note = f"ikke behandlet: kørslen blev stoppet ({stop_aarsag})"
            behandlet = {r.cvr_nummer for r in resultater}
            resultater += [fejl_resultat(c, note) for c in cvr_numre if c not in behandlet]
            break

    return resultater, stop_aarsag


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m cvr_aarsvaerk_checker",
        description=(
            "Find virksomheder hvor gennemsnitligt årsværk i de seneste 6 måneder er steget "
            "med mindst 1,00 i forhold til de 6 måneder før (data fra cvr.dev)."
        ),
    )
    p.add_argument("inputfil", type=Path, help="tekst- eller CSV-fil med ét CVR-nummer pr. linje")
    p.add_argument(
        "--output-mappe", type=Path, default=Path("resultater"), help="hvor resultaterne gemmes (default: resultater/)"
    )
    p.add_argument(
        "--cache-mappe",
        type=Path,
        default=Path("data/raa_svar"),
        help="hvor rå API-svar gemmes (default: data/raa_svar/)",
    )
    p.add_argument(
        "--cache-dage", type=float, default=7, help="genbrug gemte råsvar der er højst så mange dage gamle (default: 7)"
    )
    p.add_argument("--opdater", action="store_true", help="ignorér gemte råsvar og hent alt på ny fra API'et")
    p.add_argument("--offline", action="store_true", help="lav ingen API-kald; brug kun gemte råsvar (uanset alder)")
    p.add_argument("--pause", type=float, default=0.2, help="sekunders pause efter hvert API-kald (default: 0.2)")
    p.add_argument("--timeout", type=float, default=30, help="timeout pr. API-kald i sekunder (default: 30)")
    p.add_argument("--max-genforsoeg", type=int, default=5, help="genforsøg ved 429/5xx/netværksfejl (default: 5)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.offline and args.opdater:
        print("--offline og --opdater kan ikke bruges samtidig.")
        return 1
    if not args.inputfil.is_file():
        print(f"Inputfilen findes ikke: {args.inputfil}")
        return 1

    indl = laes_cvr_numre(args.inputfil)
    print(
        f"Indlæst {args.inputfil}: {len(indl.gyldige)} gyldige CVR-numre, "
        f"{len(indl.ugyldige)} ugyldige, {indl.antal_dubletter} dubletter fjernet."
    )
    if not indl.gyldige and not indl.ugyldige:
        print("Ingen CVR-numre fundet i filen.")
        return 1

    noegle = None
    if not args.offline:
        try:
            noegle = hent_api_noegle()
        except FatalApiFejl as e:
            print(f"Fejl: {e}")
            return 2
        if noegle is None:
            print(f"Bemærk: {MILJOEVARIABEL} er ikke sat – forventer at miljøet selv indsætter nøglen.")

    klient = CvrDevKlient(
        noegle,
        timeout=args.timeout,
        max_genforsoeg=args.max_genforsoeg,
        pause=args.pause,
    )
    resultater, stop_aarsag = koer(
        indl.gyldige,
        klient=klient,
        cache=RaaSvarCache(args.cache_mappe),
        offline=args.offline,
        opdater=args.opdater,
        cache_dage=args.cache_dage,
    )
    resultater += [fejl_resultat(raa, "ugyldigt CVR-nummer (skal være 8 cifre)") for raa in indl.ugyldige]

    mappe = args.output_mappe / datetime.now().strftime("%Y-%m-%d_%H%M%S")
    matches_sti, alle_sti = skriv_resultater(mappe, resultater)

    taelling = Counter(r.status for r in resultater)
    print()
    print("Resultat:")
    for status in (MATCH, IKKE_MATCH, UTILSTRAEKKELIGE_DATA, FEJL):
        print(f"  {status:<22} {taelling[status]}")
    print(f"  API-kald foretaget (inkl. genforsøg og nøgletest): {klient.antal_kald}")
    print(f"  {matches_sti}")
    print(f"  {alle_sti}")
    if stop_aarsag:
        print(f"\nKørslen blev STOPPET: {stop_aarsag}")
        if "401" in stop_aarsag:
            print(f"Tip: sæt miljøvariablen {MILJOEVARIABEL} til din cvr.dev API-nøgle.")
        print("Allerede hentede svar er gemt – kør samme kommando igen, når problemet er løst.")
        return 2
    return 0
