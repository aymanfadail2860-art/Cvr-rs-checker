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
        (5.00, 15.00, MATCH, "10,00"),  # ingen øvre grænse for væksten
        (5.50, 15.50, IKKE_MATCH, "10,00"),  # stor vækst, men seneste aarsvaerk over 15,00
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


@pytest.mark.parametrize("negativ", [-1, -0.5, -0.0001])
def test_negativ_aarsvaerk_er_ugyldig(negativ: object) -> None:
    maaneder = tolv_maaneder("2026-07", [5] * 6, [7] * 6)
    maaneder["2026-05"] = negativ
    r = analyser(maaneder)
    assert r.status == UTILSTRAEKKELIGE_DATA
    assert "null/ugyldig aarsvaerk i 2026-05" in r.note


def test_minus_nul_er_gyldigt_nul() -> None:
    svar = maaneds_svar(CVR, tolv_maaneder("2026-07", [7777] * 6, [1] * 6)).replace(
        '"aarsvaerk": 7777', '"aarsvaerk": -0.0'
    )
    assert analyser_raa_svar(CVR, svar).status == MATCH


@pytest.mark.parametrize(
    ("a", "b", "forventet"),
    [
        (999_999, 1_000_000, IKKE_MATCH),  # præcis +1,00 ved advarselsgrænsen, men over 15,00
        (1_000_000, 1_000_000.5, IKKE_MATCH),
        (10**30, 10**30 + 1, IKKE_MATCH),
        (10**30, 10**30, IKKE_MATCH),
    ],
)
def test_hoeje_vaerdier_analyseres_med_advarsel(a: object, b: object, forventet: str) -> None:
    # Høje værdier analyseres (aldrig UTILSTRÆKKELIGE_DATA), men størrelsesfilteret
    # (seneste aarsvaerk <= 15,00) gør dem til IKKE_MATCH.
    r = analyser(tolv_maaneder("2026-07", [a] * 6, [b] * 6))
    assert r.status == forventet
    assert "advarsel: usædvanligt høj aarsvaerk i " in r.note
    assert formater_tal(r.absolut_aendring) in ("1,00", "0,50", "0,00")


def test_ingen_advarsel_under_graensen() -> None:
    r = analyser(tolv_maaneder("2026-07", [999_998] * 6, [999_999] * 6))
    assert r.status == IKKE_MATCH  # størrelsesfilter
    assert "advarsel" not in r.note


def test_ekstremt_stor_eksponent_kan_analyseres() -> None:
    svar = maaneds_svar(CVR, tolv_maaneder("2026-07", [7777] * 6, [8888] * 6))
    svar = svar.replace('"aarsvaerk": 7777', '"aarsvaerk": 1E+50').replace('"aarsvaerk": 8888', '"aarsvaerk": 2E+50')
    r = analyser_raa_svar(CVR, svar)
    assert r.status == IKKE_MATCH  # analyseres, men er over størrelsesgrænsen
    assert "advarsel" in r.note
    assert formater_tal(r.gennemsnit_b).startswith("2000000000")


def test_meget_stor_procent_kan_vises() -> None:
    r = analyser(tolv_maaneder("2026-07", [1e-25] + [0] * 5, [1] * 6))
    assert r.status == IKKE_MATCH  # sum(B) - sum(A) = 6 - 1e-25, altså lige under 6
    assert formater_tal(r.procent_aendring).endswith(",00")  # må ikke crashe


# --- Størrelsesfilter: seneste månedlige aarsvaerk <= 15,00 ----------------


@pytest.mark.parametrize(
    ("a", "b", "seneste", "forventet"),
    [
        ([14] * 6, [15] * 6, "15", MATCH),  # vækst +1,00, seneste 15 -> MATCH
        ([15] * 6, [16] * 6, "16", IKKE_MATCH),  # vækst +1,00, seneste 16 -> IKKE_MATCH
        ([5.5] * 6, [8] * 6, "8", MATCH),  # vækst +2,50, seneste 8 -> MATCH
        ([7.01] * 6, [8] * 6, "8", IKKE_MATCH),  # vækst +0,99, seneste 8 -> IKKE_MATCH
        ([3] * 6, [5] * 5 + [8], "8", MATCH),  # vækst +2,50 (ujævn B-periode), seneste 8
        ([6] * 6, [8] * 6, "8", MATCH),  # brugerens eksempel: vækst +2,00, seneste 8
        ([3] * 6, [4] * 6, "4", MATCH),
        ([6.2] * 6, [7] * 6, "7", IKKE_MATCH),  # brugerens eksempel: vækst +0,80, seneste 7
    ],
)
def test_stoerrelsesfilter(a: list[object], b: list[object], seneste: str, forventet: str) -> None:
    r = analyser(tolv_maaneder("2026-07", a, b))
    assert r.status == forventet
    assert r.seneste_aarsvaerk == Decimal(seneste)
    assert formater_maaned(r.seneste_aarsvaerk_periode or 0) == "2026-07"


def test_over_15_faar_note_om_stoerrelse() -> None:
    r = analyser(tolv_maaneder("2026-07", [12] * 6, [16] * 6))
    assert r.status == IKKE_MATCH
    assert formater_tal(r.absolut_aendring) == "4,00"  # 6-mod-6-beregningen er uændret
    assert "seneste aarsvaerk 16 er over 15,00" in r.note


def test_praecis_15_er_tilladt_og_lidt_over_er_ikke() -> None:
    svar = maaneds_svar(CVR, tolv_maaneder("2026-07", [10] * 6, [14] * 5 + [7777]))
    assert analyser_raa_svar(CVR, svar.replace('"aarsvaerk": 7777', '"aarsvaerk": 15.00')).status == MATCH
    # Ingen afrunding før beslutningen: 15,0001 vises som 15,00, men er over grænsen.
    r = analyser_raa_svar(CVR, svar.replace('"aarsvaerk": 7777', '"aarsvaerk": 15.0001'))
    assert r.status == IKKE_MATCH
    assert formater_tal(r.seneste_aarsvaerk) == "15,00"


def test_filteret_bruger_seneste_maaned_ikke_gennemsnittet() -> None:
    # Gennemsnit B = 19,17 (over 15), men seneste måned = 15 -> MATCH
    assert analyser(tolv_maaneder("2026-07", [10] * 6, [20] * 5 + [15])).status == MATCH
    # Gennemsnit B = 11,00 (under 15), men seneste måned = 16 -> IKKE_MATCH
    assert analyser(tolv_maaneder("2026-07", [5] * 6, [10] * 5 + [16])).status == IKKE_MATCH


@pytest.mark.parametrize("seneste", [None, "8", True, -1])
def test_ellers_match_men_seneste_aarsvaerk_mangler(seneste: object) -> None:
    r = analyser(tolv_maaneder("2026-07", [5] * 6, [8] * 5 + [seneste]))
    assert r.status == UTILSTRAEKKELIGE_DATA
    assert r.seneste_aarsvaerk is None
    assert formater_maaned(r.seneste_aarsvaerk_periode or 0) == "2026-07"
    assert "null/ugyldig aarsvaerk i 2026-07" in r.note
