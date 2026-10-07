"""Virksomhedsnavn i output. Alle tests bruger falske API-svar – ingen netværk."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from cvr_aarsvaerk_checker.analyse import FEJL, IKKE_MATCH, MATCH, UTILSTRAEKKELIGE_DATA, Resultat, fejl_resultat
from cvr_aarsvaerk_checker.api import RaaSvarCache, Svar
from cvr_aarsvaerk_checker.cli import koer, main
from cvr_aarsvaerk_checker.navne import MANGLER_NOTE, UgyldigtNavneSvar, parse_navne, tilfoej_navne
from cvr_aarsvaerk_checker.output import KOLONNER

from .hjaelpere import FalskKlient, maaneds_svar, ok, tolv_maaneder


def virksomheder(*par: tuple[str, str]) -> str:
    """Syntetisk svar fra /api/cvr/virksomhed (kun de felter, vi bruger)."""
    return json.dumps(
        [{"cvrNummer": int(cvr), "virksomhedMetadata": {"nyesteNavn": {"navn": navn}}} for cvr, navn in par],
        ensure_ascii=False,
    )


def match(cvr: str) -> Resultat:
    return Resultat(cvr_nummer=cvr, status=MATCH)


# --- parse_navne ------------------------------------------------------------


def test_parse_navne_fra_metadata_og_fallback() -> None:
    raa = json.dumps(
        [
            {"cvrNummer": 11111111, "virksomhedMetadata": {"nyesteNavn": {"navn": "Alfa ApS"}}},
            {"cvrNummer": 22222222, "virksomhedMetadata": {}, "navne": [{"navn": "Gammelt"}, {"navn": "Beta ApS"}]},
            {"cvrNummer": 33333333},  # intet navn -> udelades
        ]
    )
    assert parse_navne(raa) == {"11111111": "Alfa ApS", "22222222": "Beta ApS"}


def test_parse_navne_enkelt_objekt() -> None:
    raa = json.dumps({"cvrNummer": 11111111, "virksomhedMetadata": {"nyesteNavn": {"navn": "Alfa ApS"}}})
    assert parse_navne(raa) == {"11111111": "Alfa ApS"}


@pytest.mark.parametrize("raa", ["ikke json", '"tekst"', "42"])
def test_parse_navne_ugyldigt_svar(raa: str) -> None:
    with pytest.raises(UgyldigtNavneSvar):
        parse_navne(raa)


# --- tilfoej_navne -----------------------------------------------------------


def test_navne_hentes_10_ad_gangen_og_gemmes(tmp_path: Path) -> None:
    cvr = [str(11111100 + i) for i in range(12)]
    klient = FalskKlient(
        [
            ok(virksomheder(*[(c, f"Firma {c} ApS") for c in cvr[:10]])),
            ok(virksomheder(*[(c, f"Firma {c} ApS") for c in cvr[10:]])),
        ]
    )
    cache = RaaSvarCache(tmp_path)
    ud = tilfoej_navne([match(c) for c in cvr], klient=klient, cache=cache, udskriv=lambda _: None)
    assert [r.virksomhedsnavn for r in ud] == [f"Firma {c} ApS" for c in cvr]
    assert klient.antal_kald == 2
    assert klient.urls[0] == "https://api.cvr.dev/api/cvr/virksomhed?cvr_nummer=" + ",".join(cvr[:10])
    assert klient.urls[1].endswith("cvr_nummer=" + ",".join(cvr[10:]))

    # Næste kørsel: navnene ligger i cachen -> ingen API-kald
    igen = FalskKlient([])
    ud2 = tilfoej_navne([match(c) for c in cvr], klient=igen, cache=cache, udskriv=lambda _: None)
    assert igen.antal_kald == 0
    assert [r.virksomhedsnavn for r in ud2] == [r.virksomhedsnavn for r in ud]


def test_navne_aendrer_aldrig_status_eller_tal(tmp_path: Path) -> None:
    from cvr_aarsvaerk_checker.analyse import analyser_raa_svar

    r = analyser_raa_svar("11111111", maaneds_svar("11111111", tolv_maaneder("2026-07", [5] * 6, [7] * 6)))
    (med,) = tilfoej_navne(
        [r],
        klient=FalskKlient([ok(virksomheder(("11111111", "Alfa ApS")))]),
        cache=RaaSvarCache(tmp_path),
        udskriv=lambda _: None,
    )
    assert med.virksomhedsnavn == "Alfa ApS"
    assert (med.status, med.gennemsnit_a, med.gennemsnit_b, med.absolut_aendring, med.seneste_aarsvaerk) == (
        r.status,
        r.gennemsnit_a,
        r.gennemsnit_b,
        r.absolut_aendring,
        r.seneste_aarsvaerk,
    )


def test_fejl_raekker_slaas_ikke_op(tmp_path: Path) -> None:
    klient = FalskKlient([ok(virksomheder(("11111111", "Alfa ApS")))])
    ud = tilfoej_navne(
        [match("11111111"), fejl_resultat("22222222", "API-fejl: HTTP 404")],
        klient=klient,
        cache=RaaSvarCache(tmp_path),
        udskriv=lambda _: None,
    )
    assert klient.urls == ["https://api.cvr.dev/api/cvr/virksomhed?cvr_nummer=11111111"]
    assert ud[1].virksomhedsnavn == "" and ud[1].note == "API-fejl: HTTP 404"


def test_kun_cache_laver_ingen_kald(tmp_path: Path) -> None:
    cache = RaaSvarCache(tmp_path)
    cache.gem("11111111", json.dumps({"navn": "Alfa ApS"}))
    klient = FalskKlient([])
    ud = tilfoej_navne(
        [match("11111111"), match("22222222")], klient=klient, cache=cache, kun_cache=True, udskriv=lambda _: None
    )
    assert klient.antal_kald == 0
    assert ud[0].virksomhedsnavn == "Alfa ApS"
    assert ud[1].virksomhedsnavn == "" and ud[1].note == MANGLER_NOTE


@pytest.mark.parametrize("svar", [[(404, {}, b"")], [(500, {}, b"")] * 2, [ok("<html>")], [(401, {}, b"")]])
def test_fejl_i_navneopslag_giver_note_men_samme_status(tmp_path: Path, svar: list[Svar | BaseException]) -> None:
    resultater = [
        Resultat(cvr_nummer="11111111", status=MATCH),
        Resultat(cvr_nummer="22222222", status=UTILSTRAEKKELIGE_DATA, note="mangler måned 2026-01"),
    ]
    ud = tilfoej_navne(
        resultater, klient=FalskKlient(svar, max_genforsoeg=1), cache=RaaSvarCache(tmp_path), udskriv=lambda _: None
    )
    assert [r.status for r in ud] == [MATCH, UTILSTRAEKKELIGE_DATA]
    assert ud[0].note == MANGLER_NOTE
    assert ud[1].note == f"mangler måned 2026-01; {MANGLER_NOTE}"


# --- Hele kørslen: matches.csv har altid virksomhedsnavn ---------------------


def _laes(sti: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(sti.read_text(encoding="utf-8-sig").splitlines(), delimiter=";"))


def test_matches_csv_har_altid_virksomhedsnavn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cvr_match = ["11111111", "22222222"]
    cvr_ikke = "33333333"
    cache = RaaSvarCache(tmp_path / "cache")
    for c in cvr_match:
        cache.gem(c, maaneds_svar(c, tolv_maaneder("2026-07", [5] * 6, [7] * 6)))
    cache.gem(cvr_ikke, maaneds_svar(cvr_ikke, tolv_maaneder("2026-07", [5] * 6, [5] * 6)))

    # Navnene findes ikke i ansatte-svaret og skal hentes: ét kald for alle tre.
    klient = FalskKlient(
        [ok(virksomheder(("11111111", "Alfa Tømrer ApS"), ("22222222", "=Beta"), ("33333333", "Gamma A/S")))]
    )
    monkeypatch.setattr("cvr_aarsvaerk_checker.cli.CvrDevKlient", lambda *a, **k: klient)

    inputfil = tmp_path / "input.txt"
    inputfil.write_text("\n".join([*cvr_match, cvr_ikke, "1234"]), encoding="utf-8")
    argv = [str(inputfil), "--cache-mappe", str(tmp_path / "cache"), "--navne-mappe", str(tmp_path / "navne")]
    assert main([*argv, "--output-mappe", str(tmp_path / "ud")]) == 0
    assert klient.antal_kald == 1  # kun ét navnekald; ansatte-svarene var i cachen

    (koersel,) = (tmp_path / "ud").iterdir()
    assert KOLONNER[1] == "virksomhedsnavn"
    for fil in ("matches.csv", "alle_resultater.csv"):
        assert _laes(koersel / fil) and "virksomhedsnavn" in _laes(koersel / fil)[0]

    matches = _laes(koersel / "matches.csv")
    assert [(r["cvr_nummer"], r["virksomhedsnavn"], r["status"]) for r in matches] == [
        ("11111111", "Alfa Tømrer ApS", MATCH),
        ("22222222", "'=Beta", MATCH),  # tekst der ligner en Excel-formel neutraliseres
    ]
    alle = {r["cvr_nummer"]: r for r in _laes(koersel / "alle_resultater.csv")}
    assert alle["33333333"]["virksomhedsnavn"] == "Gamma A/S" and alle["33333333"]["status"] == IKKE_MATCH
    assert alle["1234"]["virksomhedsnavn"] == "" and alle["1234"]["status"] == FEJL

    # Genkørsel offline: navnene kommer fra cachen, stadig med i matches.csv, ingen kald.
    assert main([*argv, "--offline", "--output-mappe", str(tmp_path / "ud2")]) == 0
    (koersel2,) = (tmp_path / "ud2").iterdir()
    assert [r["virksomhedsnavn"] for r in _laes(koersel2 / "matches.csv")] == ["Alfa Tømrer ApS", "'=Beta"]
    assert klient.antal_kald == 1


def test_koer_uden_navne_cache_er_uaendret(tmp_path: Path) -> None:
    cache = RaaSvarCache(tmp_path)
    cache.gem("11111111", maaneds_svar("11111111", tolv_maaneder("2026-07", [5] * 6, [7] * 6)))
    resultater, _ = koer(["11111111"], klient=FalskKlient([]), cache=cache, udskriv=lambda _: None)
    assert resultater[0].status == MATCH and resultater[0].virksomhedsnavn == ""
