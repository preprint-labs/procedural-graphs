"""GuidanceEngine: compact compiler; unmatched uses the full graph. No live LLM."""

from procedural_graphs.graph import ProceduralGraph
from procedural_graphs.guidance import GuidanceEngine
from procedural_graphs.schema import ProcedureNode, TrajectoryStep, TransitionEdge


def _sample_graph() -> ProceduralGraph:
    g = ProceduralGraph()
    g.add_procedure(
        ProcedureNode(
            id="Start",
            name="Start",
            description="entry",
            preconditions=["playbook loaded"],
        )
    )
    g.add_procedure(ProcedureNode(id="deploy", name="Deploy", description="ship"))
    g.add_procedure(ProcedureNode(id="verify", name="Verify", description="check"))
    g.add_transition(
        TransitionEdge(
            source="Start",
            target="deploy",
            condition="env ready",
            guidance="confirm target cluster",
        )
    )
    g.add_transition(
        TransitionEdge(
            source="deploy",
            target="verify",
            condition="artifact built",
            pitfalls="skipping smoke tests",
        )
    )
    return g


def test_guidance_includes_current_name_and_outgoing_conditions() -> None:
    engine = GuidanceEngine()
    graph = _sample_graph()
    block = engine.compile(graph, [TrajectoryStep(tool_name="deploy")])
    assert block.current_procedure is not None
    assert block.current_procedure.name == "Deploy"
    assert "Deploy" in block.text
    assert "artifact built" in block.text
    assert any(e.condition == "artifact built" for e in block.valid_next)
    assert block.used_full_graph is False
    assert len(block.text) <= 800


def test_unmatched_compiles_from_full_graph() -> None:
    engine = GuidanceEngine()
    graph = _sample_graph()
    block = engine.compile(graph, [TrajectoryStep(action="not-a-node")])
    assert block.used_full_graph is True
    assert block.active_node_id is None
    assert "full graph" in block.text.lower()
    conditions = {e.condition for e in block.valid_next}
    assert "env ready" in conditions
    assert "artifact built" in conditions
    assert "Start" in block.text or "Deploy" in block.text


def test_optional_llm_callable_is_stubbed_not_live() -> None:
    def stub(_prompt: str) -> str:
        return "[PROCEDURAL GUIDANCE]\nCurrent: Deploy\nif artifact built"

    engine = GuidanceEngine(llm_callable=stub)
    block = engine.compile(_sample_graph(), [TrajectoryStep(tool_name="deploy")])
    assert "artifact built" in block.text
    assert block.current_procedure is not None
    assert block.current_procedure.name == "Deploy"
