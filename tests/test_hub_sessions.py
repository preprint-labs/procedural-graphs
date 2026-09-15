"""Hub-aware MCP helpers: playbook + task_id sessions and central mutations."""

from __future__ import annotations

from pathlib import Path

import pytest

import procedural_graphs.storage as storage
from procedural_graphs.io_yaml import load_graph, save_graph
from procedural_graphs.mcp_server import (
    PlaybookSessionHub,
    apply_hub_mutation,
    create_session,
    guidance_for,
    list_available_playbooks,
)
from procedural_graphs.schema import ProcedureNode, TransitionEdge
from procedural_graphs.graph import ProceduralGraph


def _mini_graph() -> ProceduralGraph:
    graph = ProceduralGraph()
    graph.add_procedure(ProcedureNode(id="Start", name="Start", description="entry"))
    graph.add_procedure(ProcedureNode(id="A", name="Alpha", description="work"))
    graph.add_procedure(ProcedureNode(id="End", name="End", description="done", terminal=True))
    graph.add_transition(TransitionEdge(source="Start", target="A", condition="begin"))
    graph.add_transition(TransitionEdge(source="A", target="End", condition="finish"))
    return graph


def _seed_hub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    hub = tmp_path / "hub"
    monkeypatch.setattr(storage, "CENTRAL_DIR", hub)
    package = tmp_path / "pkg"
    package.mkdir()
    save_graph(_mini_graph(), package / "feature-dev.yaml")
    save_graph(_mini_graph(), package / "bugfix.yaml")
    monkeypatch.setattr(storage, "PACKAGE_PLAYBOOKS_DIR", package)
    storage.ensure_central_hub_initialized()
    return hub


def test_list_available_playbooks_stems(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_hub(tmp_path, monkeypatch)
    assert sorted(list_available_playbooks()) == ["bugfix", "feature-dev"]


def test_guidance_and_advance_are_task_scoped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_hub(tmp_path, monkeypatch)
    hub = PlaybookSessionHub()
    first = guidance_for(hub, playbook="feature-dev", task_id="one")
    second = guidance_for(hub, playbook="feature-dev", task_id="two")
    assert first["cursor"] == "Start"
    assert second["cursor"] == "Start"

    advanced = hub.advance_procedure(next_step_id="A", task_id="one", playbook="feature-dev")
    assert advanced["ok"] is True
    assert advanced["cursor"] == "A"

    still = guidance_for(hub, playbook="feature-dev", task_id="two")
    assert still["cursor"] == "Start"
    one = guidance_for(hub, playbook="feature-dev", task_id="one")
    assert one["cursor"] == "A"


def test_apply_hub_mutation_writes_central_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_hub(tmp_path, monkeypatch)
    hub = PlaybookSessionHub()
    result = apply_hub_mutation(
        hub,
        {
            "action": "add_edge",
            "data": {
                "source": "Start",
                "target": "End",
                "relation": "LEADS_TO",
                "condition": "shortcut",
            },
        },
        playbook="feature-dev",
    )
    assert result["success"] is True
    path = storage.get_playbook_path("feature-dev")
    reloaded = load_graph(path)
    assert any(e.source == "Start" and e.target == "End" for e in reloaded.edges)
    assert path.is_relative_to(storage.CENTRAL_DIR)


def test_create_session_defaults_to_hub_playbook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_hub(tmp_path, monkeypatch)
    session = create_session()
    assert session.graph_path == storage.get_playbook_path("feature-dev")
    assert session.graph.has_node("Start")


def test_create_session_explicit_path_override(tmp_path: Path) -> None:
    path = tmp_path / "override.yaml"
    save_graph(_mini_graph(), path)
    session = create_session(path)
    assert session.graph_path == path.resolve()
