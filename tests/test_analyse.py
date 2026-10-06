"""Tests af analysemetoden med syntetiske data. Ingen API-kald."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from cvr_aarsvaerk_checker.analyse import (
    FEJL,
    IKKE_MATCH,
    MATCH,
    UTILSTRAEKKELIGE_DATA,
    analyser_raa_svar,
    formater_maaned,
)
from cvr_aarsvaerk_checker.output import formater_tal

from .hjaelpere import maaneds_svar, tolv_maaneder

CVR = "12345678"


def analyser(maaneder: dict[str, object], ekstra: list[dict[str, object]] | None = None):  # type: ignore[no-untyped-def]
    return analyser_raa_svar(CVR, maaneds_svar(CVR, maaneder, ekstra))


# --- Matchgrænsen -----------------------------------------------------------


@pytest.mark.parametrize(
    ("a", "b", "forventet_status", "vist_aendring"),
    [
        (5.50, 6.49, IKKE_MATCH, "0,99"),  # +0,99
        (5.50, 6.50, MATCH, "1,00"),  # præcis +1,00
        (5.50, 6.51, MATCH, "1,01"),  # +1,01
        (5.50, 7.00, MATCH, "1,50"),
        (5.50, 8.50, MATCH, "3,00"),
        (5.50, 15.50, MATCH, "10,00"),  # ingen øvre grænse
        (5.50, 5.50, IKKE_MATCH, "0,00"),
        (8.00, 2.00, IKKE_MATCH, "-6,00"),  # fald
    ],
)
def test_matchgraense(a: float, b: float, forventet_status: str, vist_aendring: str) -> None:
    r = analyser(tolv_maaneder("2026-07", [a] * 6, [b] * 6))
    assert r.status == forventet_status
    assert formater_tal(r.absolut_aendring) == vist_aendring


def test_praecis_1_00_med_tal_der_giver_floating_point_fejl() -> None:
    # Med almindelige floats bliver denne ændring 0,9999999999999998 -> forkert IKKE_MATCH.
    r = analyser(tolv_maaneder("2026-07", [0.1] * 3 + [2.3] * 3, [1.1] * 3 + [3.3] * 3))
    assert r.absolut_aendring == Decimal(1)
    assert r.status == MATCH


def test_0_996_er_ikke_match_selvom_det_vises_som_1_00() -> None:
    r = analyser(tolv_maaneder("2026-07", [0] * 6, [0.996] * 6))
    assert r.absolut_aendring == Decimal("0.996")
    assert formater_tal(r.absolut_aendring) == "1,00"
    assert r.status == IKKE_MATCH


def test_ujaevne_vaerdier_sum_afgoer() -> None:
    # Gennemsnit A = 30/6 = 5,00; gennemsnit B = 36/6 = 6,00 -> +1,00 = MATCH
    r = analyser(tolv_maaneder("2026-07", [1, 9, 3, 7, 5, 5], [0, 12, 6, 6, 6, 6]))
    assert r.status == MATCH
    assert r.gennemsnit_a == Decimal(5) and r.gennemsnit_b == Decimal(6)


# --- Perioder og brugerens eksempel -----------------------------------------


def test_eksempel_fra_metodebeskrivelsen() -> None:
    # Seneste måned juli 2026 -> A = aug 2025 – jan 2026, B = feb – jul 2026.
    # A: sum 50 -> 8,33 ; B: sum 57 -> 9,50 ; ændring +1,17 -> MATCH
    r = analyser(tolv_maaneder("2026-07", [8, 8, 8, 8, 9, 9], [9, 9, 9, 10, 10, 10]))
    assert formater_maaned(r.seneste_registrerede_maaned or 0) == "2026-07"
    assert formater_maaned(r.periode_a_start or 0) == "2025-08"
    assert formater_maaned(r.periode_a_slut or 0) == "2026-01"
    assert formater_maaned(r.periode_b_start or 0) == "2026-02"
    assert formater_maaned(r.periode_b_slut or 0) == "2026-07"
    assert formater_tal(r.gennemsnit_a) == "8,33"
    assert formater_tal(r.gennemsnit_b) == "9,50"
    assert formater_tal(r.absolut_aendring) == "1,17"
    assert r.status == MATCH


def test_perioder_over_aarsskifte() -> None:
    r = analyser(tolv_maaneder("2026-02", [1] * 6, [1] * 6))
    assert formater_maaned(r.periode_a_start or 0) == "2025-03"
    assert formater_maaned(r.periode_a_slut or 0) == "2025-08"
    assert formater_maaned(r.periode_b_start or 0) == "2025-09"
    assert formater_maaned(r.periode_b_slut or 0) == "2026-02"


def test_aeldre_historik_ignoreres() -> None:
    maaneder: dict[str, object] = {f"{aar}-{md:02d}": 999 for aar in range(2015, 2025) for md in range(1, 13)}
    maaneder["2016-05"] = None  # null i gammel historik er ligegyldig
    del maaneder["2017-03"]  # hul i gammel historik er ligegyldigt
    maaneder.update(tolv_maaneder("2026-07", [5] * 6, [6] * 6))
    r = analyser(maaneder)
    assert r.status == MATCH
    assert r.gennemsnit_a == Decimal(5) and r.gennemsnit_b == Decimal(6)


def test_dagens_dato_bruges_ikke_som_slutpunkt() -> None:
    # Data der slutter i 2021 analyseres stadig på virksomhedens egen seneste måned.
    r = analyser(tolv_maaneder("2021-03", [2] * 6, [4] * 6))
    assert formater_maaned(r.seneste_registrerede_maaned or 0) == "2021-03"
    assert r.status == MATCH


def test_usorteret_input_sorteres() -> None:
    maaneder = tolv_maaneder("2026-07", [1] * 6, [3] * 6)
    blandet = dict(reversed(list(maaneder.items())))
    assert analyser(blandet).status == MATCH


def test_dag_i_maaneden_ignoreres() -> None:
    svar = json.loads(maaneds_svar(CVR, tolv_maaneder("2026-07", [1] * 6, [3] * 6)))
    for post in svar["ansatte"]:
        post["dato"] = post["dato"][:8] + "15"
    assert analyser_raa_svar(CVR, json.dumps(svar)).status == MATCH


# --- Kun månedsdata ---------------------------------------------------------


def _post(dato: str, interval: str, aarsvaerk: object) -> dict[str, object]:
    return {
        "dato": dato,
        "rapporteringsinterval": interval,
        "ansatte": None,
        "ansatte_interval": None,
        "aarsvaerk": aarsvaerk,
        "aarsvaerk_interval": None,
    }


def test_kvartals_og_aarsdata_bruges_ikke() -> None:
    maaneder = tolv_maaneder("2026-07", [5] * 6, [5] * 6)
    ekstra = [_post("2026-06-01", "kvartal", 500), _post("2026-01-01", "år", 500), _post("2026-09-01", "kvartal", 1)]
    r = analyser(maaneder, ekstra)
    assert r.status == IKKE_MATCH
    assert formater_maaned(r.seneste_registrerede_maaned or 0) == "2026-07"  # ikke kvartalets 2026-09


def test_kvartalsdata_udfylder_ikke_et_hul() -> None:
    maaneder = tolv_maaneder("2026-07", [5] * 6, [7] * 6)
    del maaneder["2026-03"]
    r = analyser(maaneder, [_post("2026-03-01", "kvartal", 7)])
    assert r.status == UTILSTRAEKKELIGE_DATA


def test_kun_kvartals_og_aarsdata() -> None:
    r = analyser({}, [_post("2019-06-01", "kvartal", 10), _post("2018-01-01", "år", 9)])
    assert r.status == UTILSTRAEKKELIGE_DATA
    assert r.note == "ingen månedsdata i svaret"


# --- UTILSTRÆKKELIGE_DATA ---------------------------------------------------


def test_manglende_maaned() -> None:
    maaneder = tolv_maaneder("2026-07", [5] * 6, [7] * 6)
    del maaneder["2025-11"]
    r = analyser(maaneder)
    assert r.status == UTILSTRAEKKELIGE_DATA
    assert "mangler måned 2025-11" in r.note
    assert r.gennemsnit_a is None and r.absolut_aendring is None
    assert formater_maaned(r.periode_a_start or 0) == "2025-08"  # perioderne vises stadig


def test_null_i_aarsvaerk() -> None:
    maaneder = tolv_maaneder("2026-07", [5] * 6, [7] * 6)
    maaneder["2026-04"] = None
    r = analyser(maaneder)
    assert r.status == UTILSTRAEKKELIGE_DATA
    assert "null/ugyldig aarsvaerk i 2026-04" in r.note


@pytest.mark.parametrize("ugyldig", ["7", True, "", [], {}])
def test_ugyldig_aarsvaerk_vaerdi(ugyldig: object) -> None:
    maaneder = tolv_maaneder("2026-07", [5] * 6, [7] * 6)
    maaneder["2025-09"] = ugyldig
    assert analyser(maaneder).status == UTILSTRAEKKELIGE_DATA


def test_intervalkode_bruges_aldrig_som_erstatning() -> None:
    maaneder = tolv_maaneder("2026-07", [5] * 6, [7] * 6)
    maaneder["2026-07"] = None  # posten har stadig aarsvaerk_interval = "ANTAL_5_9"
    assert analyser(maaneder).status == UTILSTRAEKKELIGE_DATA


def test_seneste_maaned_med_null_giver_utilstraekkelige_data() -> None:
    # Strikt regel: slutpunktet er seneste registrerede måned, også selvom den er null.
    maaneder = tolv_maaneder("2026-06", [5] * 6, [7] * 6)
    maaneder["2026-07"] = None
    r = analyser(maaneder)
    assert r.status == UTILSTRAEKKELIGE_DATA
    assert formater_maaned(r.seneste_registrerede_maaned or 0) == "2026-07"


def test_soeger_ikke_tilbage_efter_aeldre_komplet_blok() -> None:
    maaneder = tolv_maaneder("2025-12", [1] * 6, [9] * 6)  # komplet blok der ville give MATCH
    maaneder.update({"2026-02": 9, "2026-03": 9})  # nyeste data har et hul (2026-01 mangler)
    r = analyser(maaneder)
    assert r.status == UTILSTRAEKKELIGE_DATA
    assert "mangler måned 2026-01" in r.note


def test_maaned_findes_flere_gange() -> None:
    maaneder = tolv_maaneder("2026-07", [5] * 6, [7] * 6)
    r = analyser(maaneder, [_post("2026-02-01", "måned", 7)])
    assert r.status == UTILSTRAEKKELIGE_DATA
    assert "flere gange: 2026-02" in r.note


def test_faerre_end_12_maaneder() -> None:
    r = analyser({f"2026-{md:02d}": 5 for md in range(1, 8)})
    assert r.status == UTILSTRAEKKELIGE_DATA


@pytest.mark.parametrize("ansatte", ["null", "[]"])
def test_ingen_historik(ansatte: str) -> None:
    r = analyser_raa_svar(CVR, f'{{"cvr_nummer": {CVR}, "ansatte": {ansatte}}}')
    assert r.status == UTILSTRAEKKELIGE_DATA


# --- Nul og procent ---------------------------------------------------------


def test_nul_er_gyldig_og_procent_tom_naar_a_er_nul() -> None:
    r = analyser(tolv_maaneder("2026-07", [0] * 6, [1] * 6))
    assert r.status == MATCH
    assert r.procent_aendring is None
    assert formater_tal(r.procent_aendring) == ""


def test_procent_er_kun_information() -> None:
    r = analyser(tolv_maaneder("2026-07", [5.5] * 6, [6.5] * 6))
    assert formater_tal(r.procent_aendring) == "18,18"
    # Stor procent, men under 1 årsværk -> IKKE_MATCH
    r2 = analyser(tolv_maaneder("2026-07", [0.1] * 6, [0.9] * 6))
    assert formater_tal(r2.procent_aendring) == "800,00"
    assert r2.status == IKKE_MATCH


# --- FEJL ved ugyldigt response --------------------------------------------


@pytest.mark.parametrize(
    "raa",
    [
        "ikke json",
        "[]",
        '"tekst"',
        '{"cvr_nummer": 12345678}',
        '{"cvr_nummer": 87654321, "ansatte": []}',
        '{"cvr_nummer": 12345678, "ansatte": "x"}',
        '{"cvr_nummer": 12345678, "ansatte": [1]}',
        '{"cvr_nummer": 12345678, "ansatte": [{"dato": "juli 2026", "rapporteringsinterval": "måned"}]}',
        '{"cvr_nummer": 12345678, "ansatte": [{"dato": "2026-13-01", "rapporteringsinterval": "måned"}]}',
    ],
)
def test_ugyldigt_response_giver_fejl(raa: str) -> None:
    r = analyser_raa_svar(CVR, raa)
    assert r.status == FEJL
    assert r.note.startswith("ugyldigt API-response")


def test_liste_med_en_virksomhed_accepteres() -> None:
    # Dokumentationen beskriver en liste; API'et svarer med ét objekt. Begge virker.
    enkelt = maaneds_svar(CVR, tolv_maaneder("2026-07", [5] * 6, [7] * 6))
    assert analyser_raa_svar(CVR, f"[{enkelt}]").status == MATCH


# --- Fund fra review: eksakthed og urealistiske værdier --------------------


def test_eksakt_ogsaa_med_mange_decimaler() -> None:
    # 6 x 0,99999999999999999999999999999 (29 cifre) er en anelse under 6. Med Decimals
    # standardpræcision (28 cifre) ville summen blive rundet op til 6 -> forkert MATCH.
    svar = maaneds_svar(CVR, tolv_maaneder("2026-07", [0] * 6, [7777] * 6))
    svar = svar.replace('"aarsvaerk": 7777', '"aarsvaerk": 0.99999999999999999999999999999')
    assert analyser_raa_svar(CVR, svar).status == IKKE_MATCH


@pytest.mark.parametrize("ugyldig", [-1, -0.5, 1_000_000, 10**30])
def test_negativ_eller_urealistisk_aarsvaerk_er_ugyldig(ugyldig: object) -> None:
    maaneder = tolv_maaneder("2026-07", [5] * 6, [7] * 6)
    maaneder["2026-05"] = ugyldig
    r = analyser(maaneder)
    assert r.status == UTILSTRAEKKELIGE_DATA
    assert "null/ugyldig aarsvaerk i 2026-05" in r.note


def test_meget_stor_procent_kan_vises() -> None:
    r = analyser(tolv_maaneder("2026-07", [1e-25] + [0] * 5, [1] * 6))
    assert r.status == IKKE_MATCH  # sum(B) - sum(A) = 6 - 1e-25, altså lige under 6
    assert formater_tal(r.procent_aendring).endswith(",00")  # må ikke crashe
