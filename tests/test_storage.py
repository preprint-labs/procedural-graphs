"""Central hub: seed policy, path resolution, and playbook listing."""

from __future__ import annotations

from pathlib import Path

import pytest

import procedural_graphs.storage as storage
from procedural_graphs.storage import (
    PACKAGE_PLAYBOOKS_DIR,
    ensure_central_hub_initialized,
    get_playbook_path,
    list_central_playbooks,
    playbooks_dir,
    sessions_dir,
)


def test_package_ships_bundled_yaml_templates() -> None:
    required = {"feature-dev", "bugfix", "safe-db-migration"}
    stems = {p.stem for p in PACKAGE_PLAYBOOKS_DIR.glob("*.yaml")}
    assert required <= stems


def test_ensure_seeds_missing_defaults_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    hub = tmp_path / "hub"
    monkeypatch.setattr(storage, "CENTRAL_DIR", hub)
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "feature-dev.yaml").write_text("entry_id: Start\nnodes: []\nedges: []\n", encoding="utf-8")
    (package / "bugfix.yaml").write_text("entry_id: Start\nnodes: []\nedges: []\n", encoding="utf-8")
    monkeypatch.setattr(storage, "PACKAGE_PLAYBOOKS_DIR", package)

    ensure_central_hub_initialized()
    custom = "entry_id: Custom\nnodes: []\nedges: []\n"
    playbooks_dir().joinpath("feature-dev.yaml").write_text(custom, encoding="utf-8")

    (package / "safe-db-migration.yaml").write_text(
        "entry_id: Start\nnodes: []\nedges: []\n", encoding="utf-8"
    )
    ensure_central_hub_initialized()

    assert playbooks_dir().joinpath("feature-dev.yaml").read_text(encoding="utf-8") == custom
    assert playbooks_dir().joinpath("bugfix.yaml").is_file()
    assert playbooks_dir().joinpath("safe-db-migration.yaml").is_file()
    assert sessions_dir().is_dir()


def test_get_playbook_path_fallback_and_stem_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = tmp_path / "hub"
    monkeypatch.setattr(storage, "CENTRAL_DIR", hub)
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "feature-dev.yaml").write_text("ok: true\n", encoding="utf-8")
    monkeypatch.setattr(storage, "PACKAGE_PLAYBOOKS_DIR", package)

    missing = get_playbook_path("does-not-exist")
    assert missing.name == "feature-dev.yaml"
    assert missing == playbooks_dir() / "feature-dev.yaml"

    explicit = get_playbook_path("feature-dev.yaml")
    assert explicit.name == "feature-dev.yaml"


def test_list_central_playbooks_returns_stems(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    hub = tmp_path / "hub"
    monkeypatch.setattr(storage, "CENTRAL_DIR", hub)
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "feature-dev.yaml").write_text("ok: true\n", encoding="utf-8")
    (package / "bugfix.yaml").write_text("ok: true\n", encoding="utf-8")
    monkeypatch.setattr(storage, "PACKAGE_PLAYBOOKS_DIR", package)

    names = list_central_playbooks()
    assert sorted(names) == ["bugfix", "feature-dev"]
