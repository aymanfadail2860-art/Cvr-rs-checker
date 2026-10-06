"""Tests af API-klienten med et falsk HTTP-lag. Ingen rigtige API-kald."""

from __future__ import annotations

import http.client
import io
import os
import time
import urllib.request

import pytest

from cvr_aarsvaerk_checker.api import (
    MILJOEVARIABEL,
    CvrDevKlient,
    FatalApiFejl,
    GenforsoegOpbrugt,
    OpslagFejl,
    RaaSvarCache,
    hent_api_noegle,
)

from .hjaelpere import FalskKlient, ok


def test_429_genforsoeges_med_exponential_backoff() -> None:
    k = FalskKlient([(429, {}, b""), (429, {}, b""), ok("{}")])
    assert k.hent_ansatte("12345678") == "{}"
    assert k.sovet == [2.0, 4.0]
    assert k.antal_kald == 3


def test_retry_after_respekteres() -> None:
    k = FalskKlient([(429, {"Retry-After": "7"}, b""), ok("{}")])
    k.hent_ansatte("12345678")
    assert k.sovet == [7.0]


def test_retry_after_har_et_loft() -> None:
    k = FalskKlient([(429, {"retry-after": "100000"}, b""), ok("{}")], max_ventetid=60)
    k.hent_ansatte("12345678")
    assert k.sovet == [60.0]


def test_5xx_efter_alle_genforsoeg_giver_fejl() -> None:
    k = FalskKlient([(503, {}, b"")] * 6, max_genforsoeg=5)
    with pytest.raises(GenforsoegOpbrugt, match="HTTP 503 efter 5 genforsøg"):
        k.hent_ansatte("12345678")
    assert k.antal_kald == 6
    assert k.sovet == [2.0, 4.0, 8.0, 16.0, 32.0]


def test_429_efter_alle_genforsoeg_giver_fejl() -> None:
    k = FalskKlient([(429, {}, b"")] * 3, max_genforsoeg=2)
    with pytest.raises(GenforsoegOpbrugt, match="HTTP 429"):
        k.hent_ansatte("12345678")


def test_timeout_og_netvaerksfejl_genforsoeges() -> None:
    k = FalskKlient([TimeoutError("timed out"), ConnectionResetError("reset"), ok("{}")])
    assert k.hent_ansatte("12345678") == "{}"
    assert k.antal_kald == 3


@pytest.mark.parametrize("status", [400, 404, 418])
def test_andre_4xx_genforsoeges_ikke(status: int) -> None:
    k = FalskKlient([(status, {}, b"")])
    with pytest.raises(OpslagFejl, match=f"HTTP {status}"):
        k.hent_ansatte("12345678")
    assert k.antal_kald == 1


@pytest.mark.parametrize("status", [401, 402, 403])
def test_noegle_og_abonnementsfejl_er_fatale(status: int) -> None:
    k = FalskKlient([(status, {}, b"")])
    with pytest.raises(FatalApiFejl, match=f"HTTP {status}"):
        k.hent_ansatte("12345678")


def test_test_noegle_fejl_er_fatal() -> None:
    k = FalskKlient([(500, {}, b"")] * 2, max_genforsoeg=1)
    with pytest.raises(FatalApiFejl, match="test af API-nøgle fejlede"):
        k.test_noegle()


def test_url_og_bearer_header() -> None:
    k = FalskKlient([ok("{}")])
    k.hent_ansatte("12345678")
    assert k.urls == ["https://api.cvr.dev/api/cvrdev/virksomhed/ansatte?cvr_nummer=12345678"]
    assert k._headers["Authorization"] == "Bearer hemmelig-test-noegle"


def test_ingen_authorization_header_uden_noegle() -> None:
    assert "Authorization" not in CvrDevKlient(None)._headers


def test_noeglen_laekker_ikke_via_repr_eller_fejl() -> None:
    k = FalskKlient([(500, {}, b"hemmelig")] * 2, max_genforsoeg=1)
    assert "hemmelig-test-noegle" not in repr(k)
    with pytest.raises(OpslagFejl) as fejl:
        k.hent_ansatte("12345678")
    assert "hemmelig-test-noegle" not in str(fejl.value)


def test_noegle_fra_miljoevariabel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(MILJOEVARIABEL, "  abc123  ")
    assert hent_api_noegle() == "abc123"
    monkeypatch.delenv(MILJOEVARIABEL)
    assert hent_api_noegle() is None


def test_ugyldig_noegle_naevnes_ikke_i_fejlbesked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(MILJOEVARIABEL, "hemmelig noegle\x07")
    with pytest.raises(FatalApiFejl) as fejl:
        hent_api_noegle()
    assert "hemmelig" not in str(fejl.value)


def test_cache_gem_hent_og_alder(tmp_path) -> None:  # type: ignore[no-untyped-def]
    cache = RaaSvarCache(tmp_path / "raa")
    assert cache.hent("12345678", 7) is None
    cache.gem("12345678", '{"a": "æøå"}')
    assert cache.hent("12345678", 7) == '{"a": "æøå"}'
    gammel = time.time() - 10 * 86400
    os.utime(cache.sti("12345678"), (gammel, gammel))
    assert cache.hent("12345678", 7) is None  # for gammel
    assert cache.hent("12345678", None) == '{"a": "æøå"}'  # alder ignoreres
    assert not list((tmp_path / "raa").glob("*.tmp"))


def test_retry_after_nan_falder_tilbage_til_backoff() -> None:
    k = FalskKlient([(429, {"Retry-After": "nan"}, b""), ok("{}")])
    k.hent_ansatte("12345678")
    assert k.sovet == [2.0]


def test_redirects_foelges_ikke() -> None:
    # urllib ville ellers sende Authorization-headeren med til den nye adresse.
    from cvr_aarsvaerk_checker.api import _OPENER, _IngenRedirect

    assert any(isinstance(h, _IngenRedirect) for h in getattr(_OPENER, "handlers", []))
    anmodning = urllib.request.Request("https://api.cvr.dev/x", headers={"Authorization": "Bearer k"})
    headers = http.client.HTTPMessage()
    headers["Location"] = "http://andet.example/"
    assert _IngenRedirect().http_error_302(anmodning, io.BytesIO(), 302, "Found", headers) is None


def test_redirect_svar_bliver_til_fejl() -> None:
    k = FalskKlient([(302, {"Location": "http://andet.example/"}, b"")])
    with pytest.raises(OpslagFejl, match="HTTP 302"):
        k.hent_ansatte("12345678")
    assert k.antal_kald == 1
