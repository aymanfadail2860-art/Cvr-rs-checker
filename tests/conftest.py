from __future__ import annotations

import urllib.request
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def ingen_netvaerk(monkeypatch: pytest.MonkeyPatch) -> None:
    """Garanti: ingen test må lave rigtige API-kald."""

    def blokeret(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Test forsøgte at lave et rigtigt netværkskald")

    monkeypatch.setattr(urllib.request, "urlopen", blokeret)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", blokeret)
