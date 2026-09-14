from __future__ import annotations

from pathlib import Path

import pytest

from procedural_graphs.graph import ProceduralGraph, StructuralValidationError
from procedural_graphs.io_yaml import dumps_yaml, load_graph, loads_yaml
from procedural_graphs.schema import GraphMutation, ProcedureNode, TransitionEdge

FIXTURE = Path(__file__).parent / "fixtures" / "minimal_graph.json"


def _chain() -> ProceduralGraph:
    g = ProceduralGraph()
    g.add_procedure(ProcedureNode(id="Start", name="Start", description="entry"))
    g.add_procedure(ProcedureNode(id="A", name="A"))
    g.add_procedure(ProcedureNode(id="B", name="B"))
    g.add_procedure(ProcedureNode(id="C", name="C", terminal=True))
    g.add_transition(TransitionEdge(source="Start", target="A", condition="go A"))
    g.add_transition(TransitionEdge(source="A", target="B", condition="go B"))
    g.add_transition(TransitionEdge(source="B", target="C", condition="go C"))
    return g


def test_add_serialize_roundtrip_and_fixture_load() -> None:
    g = _chain()
    payload = g.serialize()
    restored = ProceduralGraph.load(payload)
    assert set(restored.nodes) == {"Start", "A", "B", "C"}
    assert len(restored.edges) == 3
    assert restored.start_id() == "Start"

    from_file = load_graph(FIXTURE)
    assert from_file.start_id() == "Start"
    assert {n.id for n in from_file.nodes.values()} == {"Start", "inspect", "apply", "Done"}
    assert len(from_file.edges) == 3
    ok, errors = from_file.validate_structure()
    assert ok, errors


def test_neighborhood_default_hops_is_outgoing_two() -> None:
    g = _chain()
    two = g.neighborhood("Start", hops=2)
    assert set(two.nodes) == {"Start", "A", "B"}
    assert {e.target for e in two.edges} == {"A", "B"}
    assert "C" not in two.nodes

    one = g.neighborhood("Start", hops=1)
    assert set(one.nodes) == {"Start", "A"}


def test_missing_start_is_rejected() -> None:
    g = ProceduralGraph()
    g.add_procedure(ProcedureNode(id="only", name="only"))
    g.add_procedure(ProcedureNode(id="sink", name="sink", terminal=True))
    g.add_transition(TransitionEdge(source="only", target="sink"))
    ok, errors = g.validate_structure()
    assert not ok
    assert any("Start" in e for e in errors)
    with pytest.raises(StructuralValidationError):
        g.assert_valid()


def test_orphan_component_is_rejected() -> None:
    g = _chain()
    g.add_procedure(ProcedureNode(id="orphan", name="orphan", terminal=True))
    ok, errors = g.validate_structure()
    assert not ok
    assert any("orphan" in e for e in errors)


def test_apply_mutations_is_copy_on_write() -> None:
    g = _chain()
    candidate = g.apply_mutations(
        [
            GraphMutation(
                action="add_node",
                data={"id": "hint", "name": "hint", "terminal": True},
            ),
            GraphMutation(
                action="add_edge",
                data={"source": "A", "target": "hint", "condition": "shortcut"},
            ),
        ]
    )
    assert "hint" not in g.nodes
    assert "hint" in candidate.nodes
    assert any(e.target == "hint" for e in candidate.edges)


def test_yaml_roundtrip() -> None:
    g = load_graph(FIXTURE)
    text = dumps_yaml(g)
    restored = loads_yaml(text)
    assert restored.serialize()["entry_id"] == "Start"
    assert len(restored.nodes) == len(g.nodes)
    assert len(restored.edges) == len(g.edges)
