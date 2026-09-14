"""GraphEvolver: stub LLM mutations, validation gate, rejection memory."""

from __future__ import annotations

import json

from procedural_graphs.evolver import GraphEvolver
from procedural_graphs.graph import ProceduralGraph
from procedural_graphs.schema import ProcedureNode, TrajectoryRecord, TrajectoryStep, TransitionEdge


def _graph() -> ProceduralGraph:
    graph = ProceduralGraph()
    graph.add_procedure(ProcedureNode(id="Start", name="Start", description="entry"))
    graph.add_procedure(ProcedureNode(id="A", name="Alpha", description="work"))
    graph.add_procedure(ProcedureNode(id="End", name="End", description="done", terminal=True))
    graph.add_transition(TransitionEdge(source="Start", target="A", condition="begin"))
    graph.add_transition(TransitionEdge(source="A", target="End", condition="finish"))
    return graph


def _add_edge_json() -> str:
    return json.dumps(
        [
            {
                "action": "add_edge",
                "data": {
                    "source": "Start",
                    "target": "End",
                    "relation": "LEADS_TO",
                    "condition": "shortcut",
                    "guidance": "skip ahead when ready",
                },
                "rationale": "successful traces take a shortcut",
            }
        ]
    )


def _records() -> list[TrajectoryRecord]:
    return [
        TrajectoryRecord(
            query="ok path",
            final_success=True,
            score=1.0,
            steps=[
                TrajectoryStep(tool_name="Start", action="Start"),
                TrajectoryStep(tool_name="A", action="A"),
                TrajectoryStep(tool_name="End", action="End"),
            ],
        ),
        TrajectoryRecord(
            query="bad path",
            final_success=False,
            score=0.1,
            steps=[
                TrajectoryStep(tool_name="Start", action="Start"),
                TrajectoryStep(tool_name="A", action="A", status="error"),
            ],
        ),
    ]


def _has_shortcut(graph: ProceduralGraph) -> bool:
    return any(e.source == "Start" and e.target == "End" for e in graph.edges)


def test_evolver_applies_stub_add_edge() -> None:
    graph = _graph()
    evolver = GraphEvolver(llm_callable=lambda _prompt: _add_edge_json())
    updated = evolver.evolve(graph, _records())
    assert _has_shortcut(updated)
    assert not _has_shortcut(graph)
    assert evolver.rejection_memory == []


def test_evolver_rejects_when_validator_score_drops() -> None:
    graph = _graph()

    def validator(candidate: ProceduralGraph) -> float:
        return 1.0 if not _has_shortcut(candidate) else 0.2

    evolver = GraphEvolver(llm_callable=lambda _prompt: _add_edge_json(), validator=validator)
    updated = evolver.evolve(graph, _records())
    assert updated is graph
    assert not _has_shortcut(updated)
    assert len(evolver.rejection_memory) == 1
    assert evolver.rejection_memory[0].validation_score == 0.2
    assert evolver.rejection_memory[0].mutations[0].action == "add_edge"


def test_evolver_skips_duplicate_rejected_edits() -> None:
    graph = _graph()
    calls = {"n": 0}

    def llm(_prompt: str) -> str:
        calls["n"] += 1
        return _add_edge_json()

    def validator(candidate: ProceduralGraph) -> float:
        return 1.0 if not _has_shortcut(candidate) else 0.0

    evolver = GraphEvolver(llm_callable=llm, validator=validator)
    first = evolver.evolve(graph, _records())
    second = evolver.evolve(first, _records())
    assert first is graph
    assert second is graph
    assert len(evolver.rejection_memory) == 1
    assert calls["n"] == 2
    assert not _has_shortcut(graph)
