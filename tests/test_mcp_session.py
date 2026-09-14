"""Session helpers: apply_graph_mutation persist/reject paths without FastMCP."""

from __future__ import annotations

import json
from pathlib import Path

from procedural_graphs.io_yaml import load_graph, save_graph
from procedural_graphs.mcp_server import SessionState, apply_mutation, report_anomaly
from procedural_graphs.schema import ProcedureNode, TransitionEdge


def _graph():
    from procedural_graphs.graph import ProceduralGraph

    graph = ProceduralGraph()
    graph.add_procedure(ProcedureNode(id="Start", name="Start", description="entry"))
    graph.add_procedure(ProcedureNode(id="A", name="Alpha", description="work"))
    graph.add_procedure(ProcedureNode(id="End", name="End", description="done", terminal=True))
    graph.add_transition(TransitionEdge(source="Start", target="A", condition="begin"))
    graph.add_transition(TransitionEdge(source="A", target="End", condition="finish"))
    return graph


def _session(tmp_path: Path) -> SessionState:
    path = tmp_path / "playbook.yaml"
    save_graph(_graph(), path)
    return SessionState(graph=load_graph(path), graph_path=path)


def test_apply_mutation_persists_valid_dict(tmp_path: Path) -> None:
    session = _session(tmp_path)
    result = apply_mutation(
        session,
        {
            "action": "add_edge",
            "data": {
                "source": "Start",
                "target": "End",
                "relation": "LEADS_TO",
                "condition": "shortcut",
            },
            "rationale": "allow a skip",
        },
    )
    assert result["success"] is True
    assert result["applied_action"] == "add_edge"
    reloaded = load_graph(session.graph_path)
    assert any(e.source == "Start" and e.target == "End" for e in reloaded.edges)
    assert any(e.source == "Start" and e.target == "End" for e in session.graph.edges)


def test_apply_mutation_accepts_json_string(tmp_path: Path) -> None:
    session = _session(tmp_path)
    payload = json.dumps(
        {
            "action": "add_edge",
            "data": {
                "source": "Start",
                "target": "End",
                "relation": "LEADS_TO",
                "condition": "shortcut",
            },
        }
    )
    result = apply_mutation(session, payload)
    assert result["success"] is True
    assert result["applied_action"] == "add_edge"


def test_apply_mutation_rejects_invalid_pydantic(tmp_path: Path) -> None:
    session = _session(tmp_path)
    before = session.graph_path.read_text(encoding="utf-8")
    result = apply_mutation(session, {"action": "not_a_real_action", "data": {}})
    assert result["success"] is False
    assert "error" in result
    assert session.graph_path.read_text(encoding="utf-8") == before


def test_apply_mutation_rejects_invalid_structure_without_write(tmp_path: Path) -> None:
    session = _session(tmp_path)
    before = session.graph_path.read_text(encoding="utf-8")
    result = apply_mutation(
        session,
        {
            "action": "add_node",
            "data": {
                "id": "orphan",
                "name": "orphan",
                "description": "disconnected",
            },
        },
    )
    assert result["success"] is False
    assert "error" in result
    assert not session.graph.has_node("orphan")
    assert session.graph_path.read_text(encoding="utf-8") == before

    again = apply_mutation(
        session,
        {
            "action": "add_node",
            "data": {
                "id": "orphan",
                "name": "orphan",
                "description": "disconnected",
            },
        },
    )
    assert again["success"] is False
    assert "rejection memory" in again["error"]


def test_report_anomaly_records_without_sidecar(tmp_path: Path) -> None:
    session = _session(tmp_path)
    payload = report_anomaly(session, "tests failed after implement")
    assert payload["status"] == "anomaly_recorded"
    assert payload["action_required"] == "GRAPH_REFINEMENT"
    assert payload["issue"] == "tests failed after implement"
    assert payload["current_node"] == "Start"
    assert "apply_graph_mutation" in payload["directive"]
    assert len(session.failed_records) == 1
    assert session.failed_records[0].final_success is False
    sidecars = list(tmp_path.glob("*.anomaly.yaml"))
    assert sidecars == []
    assert not (tmp_path / "playbook.yaml.anomaly.yaml").exists()
