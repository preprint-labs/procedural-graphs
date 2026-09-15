"""Central playbook hub under ``~/.procedural-graphs`` (shared across repositories).

Seed policy (copy-missing-only):
    Bundled YAML templates in ``default_playbooks/`` are copied into
    ``~/.procedural-graphs/playbooks`` when a file of the same name is absent.
    Existing hub files are never overwritten, so user edits and cross-repo
    mutations persist. A later package release that adds e.g. ``bugfix.yaml``
    will appear in the hub without clobbering a customized ``feature-dev.yaml``.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

CENTRAL_DIR = Path.home() / ".procedural-graphs"
PACKAGE_PLAYBOOKS_DIR = Path(__file__).parent / "default_playbooks"
# Import-time snapshot; prefer playbooks_dir() so tests can monkeypatch CENTRAL_DIR.
PLAYBOOKS_DIR = CENTRAL_DIR / "playbooks"
SESSIONS_DIR = CENTRAL_DIR / "sessions"
_STATE_CACHE_NAME = "state_cache.json"


def playbooks_dir() -> Path:
    return CENTRAL_DIR / "playbooks"


def sessions_dir() -> Path:
    return CENTRAL_DIR / "sessions"


def state_cache_path() -> Path:
    return sessions_dir() / _STATE_CACHE_NAME


def ensure_central_hub_initialized() -> None:
    """Create the hub and copy any bundled templates the user does not already have."""
    dest = playbooks_dir()
    dest.mkdir(parents=True, exist_ok=True)
    sessions_dir().mkdir(parents=True, exist_ok=True)
    if not PACKAGE_PLAYBOOKS_DIR.exists():
        return
    for yaml_file in PACKAGE_PLAYBOOKS_DIR.glob("*.yaml"):
        target = dest / yaml_file.name
        if not target.exists():
            shutil.copy(yaml_file, target)


def get_playbook_path(playbook_name: str = "feature-dev") -> Path:
    """Resolve a playbook stem or filename to a hub YAML path.

    Unknown names fall back to ``feature-dev.yaml`` after seeding the hub.
    """
    ensure_central_hub_initialized()
    clean_name = playbook_name.replace(".yaml", "").replace(".yml", "")
    target = playbooks_dir() / f"{clean_name}.yaml"
    if not target.exists():
        target = playbooks_dir() / "feature-dev.yaml"
    return target


def list_central_playbooks() -> list[str]:
    ensure_central_hub_initialized()
    return sorted(f.stem for f in playbooks_dir().glob("*.yaml"))


def load_state_cache() -> dict[str, Any]:
    path = state_cache_path()
    if not path.is_file():
        return {"version": 1, "sessions": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"version": 1, "sessions": {}}
    if not isinstance(payload, dict):
        return {"version": 1, "sessions": {}}
    payload.setdefault("version", 1)
    payload.setdefault("sessions", {})
    return payload


def save_state_cache(payload: dict[str, Any]) -> None:
    sessions_dir().mkdir(parents=True, exist_ok=True)
    state_cache_path().write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
