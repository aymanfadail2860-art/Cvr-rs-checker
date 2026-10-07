"""Analysemetoden: sammenlign gennemsnitligt årsværk i to 6-måneders perioder.

Reglerne (fastlagt og godkendt):

* Kun poster med rapporteringsinterval == "måned" bruges.
* Slutpunktet er virksomhedens seneste registrerede måned (ikke dagens dato).
* De 12 kalendermåneder, der slutter i den måned, er de eneste relevante.
  Periode A = de 6 første, Periode B = de 6 seneste.
* Mangler en af de 12 måneder, findes den mere end én gang, eller er
  aarsvaerk null/ugyldig, er status UTILSTRÆKKELIGE_DATA. Der søges ikke
  længere tilbage efter en ældre komplet blok.
* Negativ aarsvaerk tæller som ugyldig. Alle andre ikke-negative tal analyseres;
  ekstremt høje værdier (>= 1.000.000) giver kun en advarsel i noten.
* MATCH hvis sum(B) - sum(A) >= 6, hvilket er præcis det samme som
  gennemsnit(B) - gennemsnit(A) >= 1,00. Tal læses som Decimal og summeres
  som brøker (Fraction), så sammenligningen altid er helt eksakt.
* Størrelsesfilter: MATCH kræver desuden, at det seneste månedlige aarsvaerk
  (virksomhedens seneste registrerede måned = slutningen af Periode B) er
  <= 15,00. Over 15,00 giver IKKE_MATCH. Filteret ændrer ikke 6-mod-6-
  beregningen. Mangler den seneste værdi eller er den ugyldig, giver den
  strikte 12-måneders-regel allerede UTILSTRÆKKELIGE_DATA.
* Procentændringen er kun informativ og er tom, hvis gennemsnit A = 0.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from decimal import MAX_EMAX, MIN_EMIN, Decimal, localcontext
from fractions import Fraction
from typing import Any

MATCH = "MATCH"
IKKE_MATCH = "IKKE_MATCH"
UTILSTRAEKKELIGE_DATA = "UTILSTRÆKKELIGE_DATA"
FEJL = "FEJL"

MAANED_INTERVAL = "måned"
ANTAL_MAANEDER = 12
PERIODE_LAENGDE = 6
MATCH_GRAENSE_SUM = 6  # 1,00 årsværk i gennemsnit * 6 måneder
ADVARSEL_AARSVAERK = Decimal(1_000_000)  # kun advarsel i noten; ændrer ikke status
MAX_SENESTE_AARSVAERK = 15  # størrelsesfilter: seneste månedlige aarsvaerk skal være <= 15,00

_DATO_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


class UgyldigtResponse(Exception):
    """API-svaret har ikke det forventede format."""


@dataclass(frozen=True)
class Resultat:
    cvr_nummer: str
    status: str
    seneste_registrerede_maaned: int | None = None
    periode_a_start: int | None = None
    periode_a_slut: int | None = None
    gennemsnit_a: Decimal | None = None
    periode_b_start: int | None = None
    periode_b_slut: int | None = None
    gennemsnit_b: Decimal | None = None
    absolut_aendring: Decimal | None = None
    procent_aendring: Decimal | None = None
    seneste_aarsvaerk: Decimal | None = None
    seneste_aarsvaerk_periode: int | None = None
    note: str = ""


@dataclass(frozen=True)
class MaanedsPost:
    maaned: int  # måneds-indeks: år * 12 + (måned - 1)
    aarsvaerk: Any  # rå værdi fra API'et; valideres først i analysen


def maaned_indeks(aar: int, maaned: int) -> int:
    return aar * 12 + (maaned - 1)


def formater_maaned(indeks: int) -> str:
    """Måneds-indeks -> 'ÅÅÅÅ-MM'."""
    return f"{indeks // 12:04d}-{indeks % 12 + 1:02d}"


def fejl_resultat(cvr_nummer: str, note: str) -> Resultat:
    return Resultat(cvr_nummer=cvr_nummer, status=FEJL, note=note)


def parse_response(cvr_nummer: str, raa_svar: str) -> list[MaanedsPost]:
    """Validér API-svarets struktur og returnér kun månedsposterne.

    Rejser UgyldigtResponse, hvis svaret ikke kan bruges. Tal læses som
    Decimal, så der aldrig sker floating-point-afrunding.
    """
    try:
        data = json.loads(raa_svar, parse_float=Decimal)
    except ValueError as e:
        raise UgyldigtResponse(f"svaret er ikke gyldig JSON ({e})") from None

    # Dokumentationen siger en liste, men API'et svarer med ét objekt.
    # Vi accepterer begge, så længe der er præcis én virksomhed.
    if isinstance(data, list):
        if len(data) != 1:
            raise UgyldigtResponse(f"forventede én virksomhed i svaret, fik {len(data)}")
        data = data[0]
    if not isinstance(data, dict):
        raise UgyldigtResponse("svaret er ikke et JSON-objekt")
    if "ansatte" not in data:
        raise UgyldigtResponse("feltet 'ansatte' mangler i svaret")

    svar_cvr = data.get("cvr_nummer")
    if svar_cvr is not None and str(svar_cvr) != cvr_nummer:
        raise UgyldigtResponse(f"svaret gælder CVR {svar_cvr}, ikke {cvr_nummer}")

    poster = data["ansatte"]
    if poster is None:
        return []
    if not isinstance(poster, list):
        raise UgyldigtResponse("feltet 'ansatte' er ikke en liste")

    maaneder: list[MaanedsPost] = []
    for post in poster:
        if not isinstance(post, dict):
            raise UgyldigtResponse("en post i 'ansatte' er ikke et objekt")
        if post.get("rapporteringsinterval") != MAANED_INTERVAL:
            continue
        dato = post.get("dato")
        m = _DATO_RE.fullmatch(dato) if isinstance(dato, str) else None
        if m is None or not 1 <= int(m.group(2)) <= 12:
            raise UgyldigtResponse(f"ugyldig dato i månedspost: {dato!r}")
        maaneder.append(
            MaanedsPost(
                maaned=maaned_indeks(int(m.group(1)), int(m.group(2))),
                aarsvaerk=post.get("aarsvaerk"),
            )
        )
    return maaneder


def _som_decimal(vaerdi: Any) -> Decimal | None:
    """Gyldig numerisk aarsvaerk -> Decimal, ellers None. 0 er gyldig."""
    if isinstance(vaerdi, bool):  # bool er en underklasse af int i Python
        return None
    if isinstance(vaerdi, int):
        tal = Decimal(vaerdi)
    elif isinstance(vaerdi, Decimal) and vaerdi.is_finite():
        tal = vaerdi
    else:
        return None
    if tal < 0:  # negativ årsværk er ugyldig data
        return None
    return tal


def _som_decimal_tal(broek: Fraction) -> Decimal:
    """Eksakt brøk -> Decimal med rigeligt mange cifre (kun til visning)."""
    with localcontext() as ctx:
        ctx.prec = 40
        ctx.Emax, ctx.Emin = MAX_EMAX, MIN_EMIN  # ingen overflow ved ekstreme værdier
        return Decimal(broek.numerator) / Decimal(broek.denominator)


def analyser_maaneder(cvr_nummer: str, maaneder: list[MaanedsPost]) -> Resultat:
    """Kør analysemetoden på en virksomheds månedsposter."""
    if not maaneder:
        return Resultat(
            cvr_nummer=cvr_nummer,
            status=UTILSTRAEKKELIGE_DATA,
            note="ingen månedsdata i svaret",
        )

    seneste = max(p.maaned for p in maaneder)
    a_start = seneste - ANTAL_MAANEDER + 1
    a_slut = a_start + PERIODE_LAENGDE - 1
    b_start = a_slut + 1
    # Saml de 12 relevante måneder. Ældre historik ignoreres helt.
    vindue: dict[int, list[Any]] = {m: [] for m in range(a_start, seneste + 1)}
    for p in maaneder:
        if p.maaned in vindue:
            vindue[p.maaned].append(p.aarsvaerk)

    seneste_vaerdier = vindue[seneste]
    grundlag = Resultat(
        cvr_nummer=cvr_nummer,
        status=UTILSTRAEKKELIGE_DATA,
        seneste_registrerede_maaned=seneste,
        periode_a_start=a_start,
        periode_a_slut=a_slut,
        periode_b_start=b_start,
        periode_b_slut=seneste,
        seneste_aarsvaerk=_som_decimal(seneste_vaerdier[0]) if len(seneste_vaerdier) == 1 else None,
        seneste_aarsvaerk_periode=seneste,
    )

    mangler: list[int] = []
    dubletter: list[int] = []
    ugyldige: list[int] = []
    vaerdier: dict[int, Fraction] = {}
    for m, fundne in vindue.items():
        if not fundne:
            mangler.append(m)
        elif len(fundne) > 1:
            dubletter.append(m)
        else:
            d = _som_decimal(fundne[0])
            if d is None:
                ugyldige.append(m)
            else:
                vaerdier[m] = Fraction(d)

    if mangler or dubletter or ugyldige:
        dele: list[str] = []
        if mangler:
            dele.append("mangler måned " + ", ".join(map(formater_maaned, mangler)))
        if dubletter:
            dele.append("måned findes flere gange: " + ", ".join(map(formater_maaned, dubletter)))
        if ugyldige:
            dele.append("null/ugyldig aarsvaerk i " + ", ".join(map(formater_maaned, ugyldige)))
        return replace(grundlag, note="; ".join(dele))

    hoeje = [m for m, v in vaerdier.items() if v >= ADVARSEL_AARSVAERK]
    advarsel = "advarsel: usædvanligt høj aarsvaerk i " + ", ".join(map(formater_maaned, hoeje)) if hoeje else ""

    sum_a = sum((vaerdier[m] for m in range(a_start, a_slut + 1)), Fraction(0))
    sum_b = sum((vaerdier[m] for m in range(b_start, seneste + 1)), Fraction(0))
    forskel = sum_b - sum_a

    # Beslutningen træffes på de eksakte værdier, aldrig på afrundede tal.
    vaekst_ok = forskel >= MATCH_GRAENSE_SUM
    stoerrelse_ok = vaerdier[seneste] <= MAX_SENESTE_AARSVAERK
    status = MATCH if vaekst_ok and stoerrelse_ok else IKKE_MATCH
    stoerrelse_note = ""
    if vaekst_ok and not stoerrelse_ok:
        vist = str(grundlag.seneste_aarsvaerk).replace(".", ",")
        stoerrelse_note = f"vækstkrav opfyldt, men seneste aarsvaerk {vist} er over {MAX_SENESTE_AARSVAERK},00"
    procent = None if sum_a == 0 else _som_decimal_tal(forskel / sum_a * 100)

    return replace(
        grundlag,
        status=status,
        gennemsnit_a=_som_decimal_tal(sum_a / PERIODE_LAENGDE),
        gennemsnit_b=_som_decimal_tal(sum_b / PERIODE_LAENGDE),
        absolut_aendring=_som_decimal_tal(forskel / PERIODE_LAENGDE),
        procent_aendring=procent,
        note="; ".join(
            n
            for n in (
                stoerrelse_note,
                advarsel,
                "" if procent is not None else "procent kan ikke beregnes (gennemsnit A = 0)",
            )
            if n
        ),
    )


def analyser_raa_svar(cvr_nummer: str, raa_svar: str) -> Resultat:
    """Parse og analysér et råt API-svar. Ugyldigt format giver FEJL."""
    try:
        maaneder = parse_response(cvr_nummer, raa_svar)
    except UgyldigtResponse as e:
        return fejl_resultat(cvr_nummer, f"ugyldigt API-response: {e}")
    return analyser_maaneder(cvr_nummer, maaneder)
