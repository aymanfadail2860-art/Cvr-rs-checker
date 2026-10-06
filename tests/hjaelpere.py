"""Hjælpere til syntetiske testdata. Ingen af dem laver netværkskald."""

from __future__ import annotations

import json
from typing import Any

from cvr_aarsvaerk_checker.api import CvrDevKlient, Svar


def maaneds_svar(cvr: str, maaneder: dict[str, Any], ekstra: list[dict[str, Any]] | None = None) -> str:
    """Byg et syntetisk cvr.dev-svar. maaneder: {"2026-07": 5.5, ...}."""
    poster: list[dict[str, Any]] = [
        {
            "dato": f"{ym}-01",
            "rapporteringsinterval": "måned",
            "ansatte": None,
            "ansatte_interval": None,
            "aarsvaerk": v,
            "aarsvaerk_interval": "ANTAL_5_9",
        }
        for ym, v in maaneder.items()
    ]
    poster += ekstra or []
    poster.sort(key=lambda p: p["dato"], reverse=True)  # som API'et: nyeste først
    return json.dumps({"cvr_nummer": int(cvr), "ansatte": poster}, ensure_ascii=False)


def tolv_maaneder(slut: str, a: list[Any], b: list[Any]) -> dict[str, Any]:
    """12 sammenhængende måneder der slutter i `slut` (ÅÅÅÅ-MM): 6 A-værdier + 6 B-værdier."""
    assert len(a) == 6 and len(b) == 6
    aar, md = map(int, slut.split("-"))
    idx = aar * 12 + md - 1
    maaneder = [f"{(i // 12):04d}-{i % 12 + 1:02d}" for i in range(idx - 11, idx + 1)]
    return dict(zip(maaneder, a + b, strict=True))


class FalskKlient(CvrDevKlient):
    """CvrDevKlient hvor HTTP-laget er erstattet af en liste af foruddefinerede svar."""

    def __init__(self, svar: list[Svar | BaseException], **kwargs: Any) -> None:
        kwargs.setdefault("pause", 0)
        self.sovet: list[float] = []
        super().__init__("hemmelig-test-noegle", sove=self.sovet.append, **kwargs)
        self._svar = list(svar)
        self.urls: list[str] = []

    def _send(self, url: str) -> Svar:
        self.urls.append(url)
        naeste = self._svar.pop(0)
        if isinstance(naeste, BaseException):
            raise naeste
        return naeste


def ok(krop: str) -> Svar:
    return 200, {"Content-Type": "application/json"}, krop.encode("utf-8")


NOEGLE_OK: Svar = (200, {}, b'{"user_id": "00000000-0000-0000-0000-000000000000"}')
