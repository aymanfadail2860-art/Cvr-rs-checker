"""Tests af selve kørslen og CSV-output, med falsk API og midlertidige mapper."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from cvr_aarsvaerk_checker.analyse import FEJL, IKKE_MATCH, MATCH, UTILSTRAEKKELIGE_DATA
from cvr_aarsvaerk_checker.api import RaaSvarCache, Svar
from cvr_aarsvaerk_checker.cli import MAX_FEJL_I_TRAEK, koer, main
from cvr_aarsvaerk_checker.output import KOLONNER

from .hjaelpere import NOEGLE_OK, FalskKlient, maaneds_svar, ok, tolv_maaneder

MATCH_SVAR = maaneds_svar("11111111", tolv_maaneder("2026-07", [5] * 6, [6] * 6))
IKKE_MATCH_SVAR = maaneds_svar("22222222", tolv_maaneder("2026-07", [5] * 6, [5.99] * 6))


def _koer(cvr: list[str], klient: FalskKlient, cache: RaaSvarCache, **kw):  # type: ignore[no-untyped-def]
    return koer(cvr, klient=klient, cache=cache, udskriv=lambda _: None, **kw)


def test_api_fejl_giver_status_fejl(tmp_path: Path) -> None:
    klient = FalskKlient([NOEGLE_OK, (404, {}, b""), ok(MATCH_SVAR)])
    resultater, stop = _koer(["33333333", "11111111"], klient, RaaSvarCache(tmp_path))
    assert stop is None
    assert [r.status for r in resultater] == [FEJL, MATCH]
    assert "HTTP 404" in resultater[0].note


def test_429_efter_retries_giver_fejl_og_fortsaetter(tmp_path: Path) -> None:
    klient = FalskKlient([NOEGLE_OK, *[(429, {}, b"")] * 3, ok(MATCH_SVAR)], max_genforsoeg=2)
    resultater, stop = _koer(["33333333", "11111111"], klient, RaaSvarCache(tmp_path))
    assert stop is None
    assert [r.status for r in resultater] == [FEJL, MATCH]
    assert "HTTP 429 efter 2 genforsøg" in resultater[0].note


def test_ugyldigt_response_giver_fejl_og_gemmes_ikke(tmp_path: Path) -> None:
    cache = RaaSvarCache(tmp_path)
    klient = FalskKlient([NOEGLE_OK, ok("<html>fejl</html>")])
    resultater, _ = _koer(["11111111"], klient, cache)
    assert resultater[0].status == FEJL
    assert not cache.sti("11111111").exists()


def test_genstart_bruger_gemte_svar_uden_nye_kald(tmp_path: Path) -> None:
    cache = RaaSvarCache(tmp_path)
    foerste = FalskKlient([NOEGLE_OK, ok(MATCH_SVAR), ok(IKKE_MATCH_SVAR)])
    _koer(["11111111", "22222222"], foerste, cache)
    assert foerste.antal_kald == 3

    anden = FalskKlient([])  # ville fejle ved ethvert kald
    resultater, _ = _koer(["11111111", "22222222"], anden, cache)
    assert anden.antal_kald == 0
    assert [r.status for r in resultater] == [MATCH, IKKE_MATCH]


def test_opdater_ignorerer_cache(tmp_path: Path) -> None:
    cache = RaaSvarCache(tmp_path)
    cache.gem("11111111", IKKE_MATCH_SVAR.replace("22222222", "11111111"))
    klient = FalskKlient([NOEGLE_OK, ok(MATCH_SVAR)])
    resultater, _ = _koer(["11111111"], klient, cache, opdater=True)
    assert resultater[0].status == MATCH


def test_offline_uden_cache_giver_fejl(tmp_path: Path) -> None:
    klient = FalskKlient([])
    resultater, _ = _koer(["11111111"], klient, RaaSvarCache(tmp_path), offline=True)
    assert resultater[0].status == FEJL
    assert "offline" in resultater[0].note
    assert klient.antal_kald == 0


def test_fatal_fejl_stopper_og_resten_markeres(tmp_path: Path) -> None:
    klient = FalskKlient([NOEGLE_OK, ok(MATCH_SVAR), (403, {}, b"")])
    resultater, stop = _koer(["11111111", "22222222", "33333333"], klient, RaaSvarCache(tmp_path))
    assert stop is not None and "HTTP 403" in stop
    assert [r.status for r in resultater] == [MATCH, FEJL, FEJL]
    assert all("ikke behandlet" in r.note for r in resultater[1:])


def test_forkert_noegle_stopper_foer_forbrug(tmp_path: Path) -> None:
    klient = FalskKlient([(401, {}, b"")])
    resultater, stop = _koer(["11111111", "22222222"], klient, RaaSvarCache(tmp_path))
    assert stop is not None and "401" in stop
    assert klient.urls == ["https://api.cvr.dev/api/test/apikey"]  # kun det gratis kald
    assert [r.status for r in resultater] == [FEJL, FEJL]


def test_mange_fejl_i_traek_stopper_koerslen(tmp_path: Path) -> None:
    cvr = [f"{10000000 + i}" for i in range(MAX_FEJL_I_TRAEK + 3)]
    klient = FalskKlient([NOEGLE_OK, *[(500, {}, b"")] * 100], max_genforsoeg=0)
    resultater, stop = _koer(cvr, klient, RaaSvarCache(tmp_path))
    assert stop is not None and "i træk" in stop
    assert len(resultater) == len(cvr)
    assert klient.antal_kald == 1 + MAX_FEJL_I_TRAEK


def test_uventet_fejl_giver_fejl_status(tmp_path: Path) -> None:
    class OedelagtCache(RaaSvarCache):
        def hent(self, cvr_nummer: str, max_alder_dage: float | None) -> str | None:
            raise RuntimeError("uventet")

    resultater, stop = _koer(["11111111"], FalskKlient([]), OedelagtCache(tmp_path))
    assert stop is None
    assert resultater[0].status == FEJL
    assert "teknisk fejl: RuntimeError" in resultater[0].note


def test_cache_kan_ikke_skrives_stopper_men_beholder_resultat(tmp_path: Path) -> None:
    class SkrivebeskyttetCache(RaaSvarCache):
        def gem(self, cvr_nummer: str, raa_svar: str) -> None:
            raise PermissionError("disk skrivebeskyttet")

    klient = FalskKlient([NOEGLE_OK, ok(MATCH_SVAR)])
    resultater, stop = _koer(["11111111", "22222222"], klient, SkrivebeskyttetCache(tmp_path))
    assert stop is not None and "kan ikke gemmes" in stop
    assert resultater[0].status == MATCH  # det betalte opslag smides ikke væk
    assert "råsvar kunne ikke gemmes" in resultater[0].note
    assert resultater[1].status == FEJL and "ikke behandlet" in resultater[1].note
    assert klient.antal_kald == 2  # ingen flere opslag efter stop


def test_oedelagt_gemt_fil_hentes_igen(tmp_path: Path) -> None:
    cache = RaaSvarCache(tmp_path)
    cache.gem("11111111", "")
    klient = FalskKlient([NOEGLE_OK, ok(MATCH_SVAR)])
    resultater, _ = _koer(["11111111"], klient, cache)
    assert resultater[0].status == MATCH
    assert cache.hent("11111111", None) == MATCH_SVAR


def test_ctrl_c_stopper_paent(tmp_path: Path) -> None:
    klient = FalskKlient([NOEGLE_OK, ok(MATCH_SVAR), KeyboardInterrupt()])
    resultater, stop = _koer(["11111111", "22222222", "33333333"], klient, RaaSvarCache(tmp_path))
    assert stop is not None and "Ctrl+C" in stop
    assert [r.status for r in resultater] == [MATCH, FEJL, FEJL]


def test_fejl_i_traek_nulstilles_naar_api_svarer(tmp_path: Path) -> None:
    moenster: list[Svar] = [(503, {}, b""), (404, {}, b"")] * MAX_FEJL_I_TRAEK
    cvr = [f"{10000000 + i}" for i in range(len(moenster))]
    klient = FalskKlient([NOEGLE_OK, *moenster], max_genforsoeg=0)
    resultater, stop = _koer(cvr, klient, RaaSvarCache(tmp_path))
    assert stop is None
    assert len(resultater) == len(cvr)


def test_efter_stop_bruges_gemte_svar_stadig(tmp_path: Path) -> None:
    cache = RaaSvarCache(tmp_path)
    cache.gem("11111111", MATCH_SVAR)
    klient = FalskKlient([(401, {}, b"")])
    resultater, stop = _koer(["33333333", "11111111"], klient, cache)
    assert stop is not None
    assert [r.status for r in resultater] == [FEJL, MATCH]
    assert klient.antal_kald == 1


# --- Hele programmet, offline med gemte svar --------------------------------


def _laes_csv(sti: Path) -> list[list[str]]:
    raa = sti.read_bytes()
    assert raa.startswith(b"\xef\xbb\xbf")  # BOM, så Excel læser UTF-8 korrekt
    return list(csv.reader(raa.decode("utf-8-sig").splitlines(), delimiter=";"))


def test_main_offline_skriver_begge_csv_filer(tmp_path: Path) -> None:
    cache = RaaSvarCache(tmp_path / "cache")
    cache.gem("11111111", MATCH_SVAR)
    cache.gem("22222222", IKKE_MATCH_SVAR)
    huller = tolv_maaneder("2026-07", [5] * 6, [9] * 6)
    del huller["2026-01"]
    cache.gem("44444444", maaneds_svar("44444444", huller))

    inputfil = tmp_path / "input.csv"
    inputfil.write_text(
        "Navn;CVR-nummer\nA ApS;11111111\nB ApS;DK 2222 2222\nC ApS;11111111\n"
        "D ApS;1234\nE ApS;44444444\nF ApS;55555555\n",
        encoding="utf-8",
    )
    navne = RaaSvarCache(tmp_path / "navne")
    for cvr, navn in [("11111111", "Alfa Tømrer ApS"), ("22222222", "Beta Byg ApS"), ("44444444", "Gamma A/S")]:
        navne.gem(cvr, json.dumps({"navn": navn}))
    kode = main(
        [
            str(inputfil),
            "--offline",
            "--cache-mappe",
            str(tmp_path / "cache"),
            "--navne-mappe",
            str(tmp_path / "navne"),
            "--output-mappe",
            str(tmp_path / "ud"),
        ]
    )
    assert kode == 0

    (koersel,) = (tmp_path / "ud").iterdir()
    alle = _laes_csv(koersel / "alle_resultater.csv")
    assert alle[0] == KOLONNER
    status = {r[0]: r[KOLONNER.index("status")] for r in alle[1:]}
    assert status == {
        "11111111": MATCH,
        "22222222": IKKE_MATCH,
        "44444444": UTILSTRAEKKELIGE_DATA,
        "55555555": FEJL,  # intet gemt svar i offline-tilstand
        "1234": FEJL,  # ugyldigt CVR-nummer
    }  # dubletten 11111111 er fjernet

    matches = _laes_csv(koersel / "matches.csv")
    assert [r[0] for r in matches[1:]] == ["11111111"]
    raekke = dict(zip(KOLONNER, matches[1], strict=True))
    assert raekke == {
        "cvr_nummer": "11111111",
        "virksomhedsnavn": "Alfa Tømrer ApS",
        "seneste_registrerede_maaned": "2026-07",
        "periode_a_start": "2025-08",
        "periode_a_slut": "2026-01",
        "gennemsnit_aarsvaerk_periode_a": "5,00",
        "periode_b_start": "2026-02",
        "periode_b_slut": "2026-07",
        "gennemsnit_aarsvaerk_periode_b": "6,00",
        "absolut_aendring": "1,00",
        "procent_aendring": "20,00",
        "seneste_aarsvaerk": "6,00",
        "seneste_aarsvaerk_periode": "2026-07",
        "status": MATCH,
        "note": "",
    }


def test_formler_fra_input_neutraliseres_i_csv(tmp_path: Path) -> None:
    inputfil = tmp_path / "input.txt"
    inputfil.write_text('CVR\n=HYPERLINK("http://x")\n@SUM(1+1)\n+45 12\n', encoding="utf-8")
    args = [
        str(inputfil),
        "--offline",
        "--navne-mappe",
        str(tmp_path / "navne"),
        "--output-mappe",
        str(tmp_path / "ud"),
    ]
    assert main(args) == 0
    (koersel,) = (tmp_path / "ud").iterdir()
    celler = [r[0] for r in _laes_csv(koersel / "alle_resultater.csv")[1:]]
    assert all(c.startswith("'") for c in celler), celler


def test_matches_csv_udelader_virksomheder_over_15_aarsvaerk(tmp_path: Path) -> None:
    cache = RaaSvarCache(tmp_path / "cache")
    cache.gem("11111111", MATCH_SVAR)  # vækst +1,00, seneste 6 -> MATCH
    for_stor = maaneds_svar("33333333", tolv_maaneder("2026-07", [20] * 6, [24] * 6))  # vækst +4, seneste 24
    cache.gem("33333333", for_stor)
    inputfil = tmp_path / "input.txt"
    inputfil.write_text("11111111\n33333333\n", encoding="utf-8")
    kode = main(
        [
            str(inputfil),
            "--offline",
            "--cache-mappe",
            str(tmp_path / "cache"),
            "--navne-mappe",
            str(tmp_path / "navne"),
            "--output-mappe",
            str(tmp_path / "ud"),
        ]
    )
    assert kode == 0
    (koersel,) = (tmp_path / "ud").iterdir()
    matches = _laes_csv(koersel / "matches.csv")
    assert [r[0] for r in matches[1:]] == ["11111111"]
    alle = {r[0]: dict(zip(KOLONNER, r, strict=True)) for r in _laes_csv(koersel / "alle_resultater.csv")[1:]}
    assert alle["33333333"]["status"] == IKKE_MATCH
    assert alle["33333333"]["absolut_aendring"] == "4,00"
    assert alle["33333333"]["seneste_aarsvaerk"] == "24,00"
    assert alle["33333333"]["seneste_aarsvaerk_periode"] == "2026-07"
