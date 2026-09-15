"""Isolate the central hub so tests never write to ~/.procedural-graphs."""

from __future__ import annotations

from pathlib import Path

import pytest

import procedural_graphs.storage as storage


@pytest.fixture(autouse=True)
def isolate_central_hub(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    hub = tmp_path_factory.mktemp("procedural_graphs_hub")
    monkeypatch.setattr(storage, "CENTRAL_DIR", hub)
    return hub
