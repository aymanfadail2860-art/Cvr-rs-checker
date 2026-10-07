"""Klient til cvr.dev's endpoint for ansatte og årsværk, plus lokal cache af råsvar.

API-nøglen:
* Læses fra miljøvariablen CVR_DEV_API_KEY og sendes som
  "Authorization: Bearer <nøgle>".
* Er variablen ikke sat, sendes ingen Authorization-header. Det bruges i
  miljøer, hvor en proxy selv indsætter den tilknyttede credential.
* Nøglen skrives aldrig til log, output, fejlbeskeder eller filer.
"""

from __future__ import annotations

import http.client
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

BASIS_URL = "https://api.cvr.dev"
ANSATTE_STI = "/api/cvrdev/virksomhed/ansatte"
VIRKSOMHED_STI = "/api/cvr/virksomhed"  # rå CVR-data; bruges kun til virksomhedsnavne
TEST_STI = "/api/test/apikey"  # tæller ikke med i det månedlige forbrug
MILJOEVARIABEL = "CVR_DEV_API_KEY"

_FATALE_STATUSKODER = {
    401: "API-nøglen er ugyldig eller bliver ikke medsendt (HTTP 401)",
    402: "API-nøglen er ikke tilknyttet et aktivt abonnement (HTTP 402)",
    403: "endpointet for ansatte og årsværk er ikke inkluderet i abonnementet (HTTP 403)",
}


class OpslagFejl(Exception):
    """Et enkelt opslag kunne ikke gennemføres. Virksomheden får status FEJL."""


class GenforsoegOpbrugt(OpslagFejl):
    """429/5xx/netværksfejl blev ved, også efter alle genforsøg."""


class FatalApiFejl(Exception):
    """Fejl, der rammer alle opslag (fx ugyldig nøgle). Kørslen stoppes."""


Svar = tuple[int, dict[str, str], bytes]


class _IngenRedirect(urllib.request.HTTPRedirectHandler):
    """Følg aldrig redirects: urllib ville sende Authorization-headeren med til den nye adresse."""

    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


_OPENER = urllib.request.build_opener(_IngenRedirect)


def hent_api_noegle() -> str | None:
    noegle = os.environ.get(MILJOEVARIABEL, "").strip()
    if not noegle:
        return None
    if not noegle.isascii() or not noegle.isprintable() or " " in noegle:
        # Nøglen selv må aldrig med i beskeden.
        raise FatalApiFejl(f"{MILJOEVARIABEL} indeholder ugyldige tegn")
    return noegle


class CvrDevKlient:
    def __init__(
        self,
        api_noegle: str | None,
        *,
        timeout: float = 30.0,
        max_genforsoeg: int = 5,
        backoff_basis: float = 2.0,
        max_ventetid: float = 120.0,
        pause: float = 0.2,
        sove: Callable[[float], None] = time.sleep,
    ) -> None:
        self._headers = {"Accept": "application/json", "User-Agent": "cvr-aarsvaerk-checker/1.0"}
        if api_noegle:
            self._headers["Authorization"] = f"Bearer {api_noegle}"
        self.timeout = timeout
        self.max_genforsoeg = max_genforsoeg
        self.backoff_basis = backoff_basis
        self.max_ventetid = max_ventetid
        self.pause = pause
        self._sove = sove
        self.antal_kald = 0  # rigtige HTTP-kald, inkl. genforsøg

    def __repr__(self) -> str:  # undgå at nøglen kan dukke op via repr()
        return f"CvrDevKlient(timeout={self.timeout}, max_genforsoeg={self.max_genforsoeg})"

    def _send(self, url: str) -> Svar:
        """Ét HTTP GET. Netværksfejl rejses som OSError/HTTPException."""
        anmodning = urllib.request.Request(url, headers=self._headers, method="GET")
        try:
            with _OPENER.open(anmodning, timeout=self.timeout) as svar:
                return svar.status, dict(svar.headers.items()), svar.read()
        except urllib.error.HTTPError as e:
            with e:
                return e.code, dict(e.headers.items()) if e.headers else {}, e.read()

    def _ventetid(self, forsoeg: int, headers: dict[str, str]) -> float:
        retry_after = next((v for k, v in headers.items() if k.lower() == "retry-after"), None)
        if retry_after is not None:
            try:
                sekunder = float(retry_after)
                if math.isfinite(sekunder):
                    return min(max(sekunder, 0.0), self.max_ventetid)
            except ValueError:
                pass  # HTTP-dato-format understøttes ikke; brug backoff
        return min(self.backoff_basis * 2.0**forsoeg, self.max_ventetid)

    def _hent(self, sti: str, params: dict[str, str] | None = None) -> str:
        url = BASIS_URL + sti
        if params:
            url += "?" + urllib.parse.urlencode(params, safe=",")

        sidste_fejl = ""
        ventetid = 0.0
        for forsoeg in range(self.max_genforsoeg + 1):
            if forsoeg:
                self._sove(ventetid)
            self.antal_kald += 1
            try:
                status, headers, krop = self._send(url)
            except (OSError, http.client.HTTPException) as e:  # timeout, forbindelse m.m.
                sidste_fejl = f"netværksfejl: {type(e).__name__}: {e}"
                ventetid = self._ventetid(forsoeg, {})
                continue
            finally:
                if self.pause:
                    self._sove(self.pause)

            if status == 200:
                try:
                    return krop.decode("utf-8")
                except UnicodeDecodeError:
                    raise OpslagFejl("ugyldigt API-response: ikke UTF-8") from None
            if status in _FATALE_STATUSKODER:
                raise FatalApiFejl(_FATALE_STATUSKODER[status])
            if status == 429 or 500 <= status <= 599:
                sidste_fejl = f"HTTP {status}"
                ventetid = self._ventetid(forsoeg, headers)
                continue
            if status == 404:
                raise OpslagFejl("API-fejl: CVR-nummeret blev ikke fundet (HTTP 404)")
            raise OpslagFejl(f"API-fejl: HTTP {status}")

        raise GenforsoegOpbrugt(f"{sidste_fejl} efter {self.max_genforsoeg} genforsøg")

    def test_noegle(self) -> None:
        """Gratis kald, der bekræfter at nøglen virker. Rejser FatalApiFejl ellers."""
        try:
            krop = self._hent(TEST_STI)
            json.loads(krop)
        except OpslagFejl as e:
            raise FatalApiFejl(f"test af API-nøgle fejlede: {e}") from None
        except ValueError:
            raise FatalApiFejl("test af API-nøgle gav et ugyldigt svar") from None

    def hent_ansatte(self, cvr_nummer: str) -> str:
        """Hent det rå JSON-svar for ét CVR-nummer."""
        return self._hent(ANSATTE_STI, {"cvr_nummer": cvr_nummer})

    def hent_virksomheder(self, cvr_numre: list[str]) -> str:
        """Hent rå CVR-data for op til 10 CVR-numre i ét kald (bruges til navne)."""
        return self._hent(VIRKSOMHED_STI, {"cvr_nummer": ",".join(cvr_numre)})


class RaaSvarCache:
    """Gemmer råsvar som <mappe>/<cvr>.json, så en kørsel kan genstartes."""

    def __init__(self, mappe: Path) -> None:
        self.mappe = mappe

    def sti(self, cvr_nummer: str) -> Path:
        return self.mappe / f"{cvr_nummer}.json"

    def hent(self, cvr_nummer: str, max_alder_dage: float | None) -> str | None:
        """Returnér gemt råsvar, eller None hvis det mangler/er for gammelt."""
        sti = self.sti(cvr_nummer)
        try:
            if max_alder_dage is not None:
                alder = time.time() - sti.stat().st_mtime
                if alder > max_alder_dage * 86400:
                    return None
            return sti.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    def gem(self, cvr_nummer: str, raa_svar: str) -> None:
        self.mappe.mkdir(parents=True, exist_ok=True)
        sti = self.sti(cvr_nummer)
        midlertidig = sti.with_suffix(".tmp")
        midlertidig.write_text(raa_svar, encoding="utf-8")
        midlertidig.replace(sti)  # atomisk: en afbrudt kørsel efterlader ikke halve filer
