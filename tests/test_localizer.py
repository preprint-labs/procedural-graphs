"""NodeLocalizer: empty → Start; tool-name match; unmatched → None."""

from procedural_graphs.graph import ProceduralGraph
from procedural_graphs.localizer import NodeLocalizer
from procedural_graphs.schema import ProcedureNode, TrajectoryStep, TransitionEdge


def _sample_graph() -> ProceduralGraph:
    g = ProceduralGraph()
    g.add_procedure(ProcedureNode(id="Start", name="Start", description="entry"))
    g.add_procedure(ProcedureNode(id="deploy", name="Deploy", description="ship"))
    g.add_procedure(ProcedureNode(id="verify", name="Verify", description="check"))
    g.add_transition(
        TransitionEdge(source="Start", target="deploy", condition="env ready")
    )
    g.add_transition(
        TransitionEdge(source="deploy", target="verify", condition="artifact built")
    )
    return g


def test_empty_trajectory_locates_start() -> None:
    loc = NodeLocalizer()
    assert loc.locate(_sample_graph(), []) == "Start"
    assert loc.locate(_sample_graph(), None) == "Start"


def test_tool_name_matches_node_id_or_name() -> None:
    loc = NodeLocalizer()
    graph = _sample_graph()
    by_id = loc.locate(graph, [TrajectoryStep(tool_name="deploy")])
    by_name = loc.locate(graph, [TrajectoryStep(action="Verify")])
    assert by_id == "deploy"
    assert by_name == "verify"


def test_unmatched_returns_none() -> None:
    loc = NodeLocalizer()
    assert loc.locate(_sample_graph(), [TrajectoryStep(tool_name="unknown_tool")]) is None
