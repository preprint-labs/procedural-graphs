"""GuidedAgent injects guidance text and records trajectory steps."""

from __future__ import annotations

from procedural_graphs.graph import ProceduralGraph
from procedural_graphs.schema import GuidanceBlock, ProcedureNode, TransitionEdge
from procedural_graphs.wrapper import GuidedAgent


def _graph() -> ProceduralGraph:
    graph = ProceduralGraph()
    graph.add_procedure(ProcedureNode(id="Start", name="Start", description="entry"))
    graph.add_procedure(ProcedureNode(id="End", name="End", description="done", terminal=True))
    graph.add_transition(TransitionEdge(source="Start", target="End", condition="ready"))
    return graph


class _StubLocalizer:
    def locate(self, graph, trajectory, k=1):
        return "Start"


class _StubGuidance:
    def compile(self, graph, trajectory=None, query="", active_node_id=None, **_kwargs):
        return GuidanceBlock(
            text="[PROCEDURAL GUIDANCE] from Start, proceed when ready",
            active_node_id=active_node_id,
            used_full_graph=False,
        )


def test_wrapper_injects_guidance_and_records_steps() -> None:
    graph = _graph()
    captured: dict = {}

    def agent_fn(query, history, guidance):
        captured["query"] = query
        captured["history"] = history
        captured["guidance"] = guidance
        return {"tool_name": "Start", "action": "Start", "output": "located", "status": "ok"}

    agent = GuidedAgent(
        agent_fn,
        graph,
        evolve=False,
        localizer=_StubLocalizer(),
        guidance_engine=_StubGuidance(),
    )
    result = agent.step("how do I finish?")
    assert result["tool_name"] == "Start"
    assert captured["query"] == "how do I finish?"
    assert captured["history"] == []
    assert "[PROCEDURAL GUIDANCE]" in captured["guidance"]
    assert len(agent.history) == 1
    assert agent.history[0].tool_name == "Start"
    assert agent.history[0].output == "located"
    assert agent.current is not None
    assert agent.current.query == "how do I finish?"
