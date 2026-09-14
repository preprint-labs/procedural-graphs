"""FastMCP overlay: soft playbook guidance over an in-process ProceduralGraph session."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from procedural_graphs.evolver import GraphEvolver
from procedural_graphs.graph import ProceduralGraph, StructuralValidationError
from procedural_graphs.guidance import GuidanceEngine
from procedural_graphs.io_yaml import load_graph, save_graph
from procedural_graphs.schema import GraphMutation, GuidanceBlock, TrajectoryRecord, TrajectoryStep

TOOL_NAMES = (
    "get_procedural_guidance",
    "advance_procedure",
    "report_procedural_anomaly",
    "apply_graph_mutation",
)

_ANOMALY_DIRECTIVE = (
    "Propose a recovery GraphMutation (add_node, delete_node, add_edge, or "
    "delete_edge) that addresses this issue, then call apply_graph_mutation "
    "with that mutation. Playbook evolution is agent-in-the-loop; do not "
    "expect this server to call an external LLM."
)


@dataclass
class SessionState:
    graph: ProceduralGraph
    graph_path: Path
    cursor: str | None = None
    trajectory: list[TrajectoryStep] = field(default_factory=list)
    failed_records: list[TrajectoryRecord] = field(default_factory=list)
    engine: GuidanceEngine = field(default_factory=GuidanceEngine)
    evolver: GraphEvolver | None = None

    def __post_init__(self) -> None:
        if self.cursor is None:
            self.cursor = self.graph.start_id()
        if self.evolver is None:
            # Rejection memory only; llm_callable is never invoked by MCP tools.
            self.evolver = GraphEvolver(llm_callable=lambda _prompt: "")


def _block_to_json(block: GuidanceBlock) -> dict[str, Any]:
    current = block.current_procedure.model_dump() if block.current_procedure else None
    return {
        "text": block.text,
        "current_procedure": current,
        "preconditions": list(block.preconditions),
        "valid_next_edges": [edge.model_dump() for edge in block.next_edges],
        "advisory_notes": list(block.advisory_notes),
        "hops": block.hops,
        "used_full_graph": block.used_full_graph,
        "active_node_id": block.active_node_id,
        "soft": True,
    }


def _compile(session: SessionState, *, active_node_id: str | None = None) -> GuidanceBlock:
    node_id = active_node_id if active_node_id is not None else session.cursor
    return session.engine.compile(
        session.graph,
        session.trajectory,
        active_node_id=node_id,
    )


def _resolve_node_id(graph: ProceduralGraph, key: str) -> str | None:
    found = graph.find_node(key)
    return found.id if found is not None else None


def _outgoing_targets(graph: ProceduralGraph, node_id: str | None) -> set[str]:
    if not node_id or not graph.has_node(node_id):
        return set()
    return {edge.target for edge in graph.outgoing(node_id)}


def coerce_graph_mutation(mutation: Any) -> GraphMutation:
    """Accept a GraphMutation, dict, JSON object/string, or a one-item list."""
    payload: Any = mutation
    if isinstance(payload, GraphMutation):
        return payload
    for _ in range(3):
        if not isinstance(payload, str):
            break
        text = payload.strip()
        if not text:
            return GraphMutation.model_validate(payload)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return GraphMutation.model_validate(payload)
    if isinstance(payload, list) and len(payload) == 1:
        payload = payload[0]
    return GraphMutation.model_validate(payload)


def report_anomaly(session: SessionState, issue_description: str) -> dict[str, Any]:
    """Record a failed trajectory in session memory; host agent must refine the graph."""
    record = TrajectoryRecord(
        steps=list(session.trajectory),
        final_success=False,
        score=0.0,
        query=issue_description,
    )
    session.failed_records.append(record)
    return {
        "status": "anomaly_recorded",
        "current_node": session.cursor,
        "issue": issue_description,
        "action_required": "GRAPH_REFINEMENT",
        "directive": _ANOMALY_DIRECTIVE,
    }


def apply_mutation(session: SessionState, mutation: Any) -> dict[str, Any]:
    """Validate, trial-apply, persist a single GraphMutation onto the active playbook."""
    try:
        mut = coerce_graph_mutation(mutation)
    except ValidationError as exc:
        return {"success": False, "error": str(exc)}

    if session.evolver is not None and session.evolver._is_rejected([mut]):
        return {
            "success": False,
            "error": (
                "Mutation rejected: this edit matches an entry in rejection memory "
                "and will not be applied again."
            ),
        }

    try:
        candidate = session.graph.apply_mutations([mut], inplace=False)
    except (KeyError, ValueError, StructuralValidationError) as exc:
        if session.evolver is not None:
            session.evolver._remember(
                [mut],
                validation_score=0.0,
                records=session.failed_records,
            )
        return {"success": False, "error": str(exc)}

    ok, errors = candidate.validate_structure()
    if not ok:
        if session.evolver is not None:
            session.evolver._remember(
                [mut],
                validation_score=0.0,
                records=session.failed_records,
            )
        return {"success": False, "error": "; ".join(errors)}

    try:
        candidate.assert_valid()
    except StructuralValidationError as exc:
        if session.evolver is not None:
            session.evolver._remember(
                [mut],
                validation_score=0.0,
                records=session.failed_records,
            )
        return {"success": False, "error": str(exc)}

    session.graph = candidate
    save_graph(session.graph, session.graph_path)
    return {
        "success": True,
        "message": f"Applied {mut.action} and persisted {session.graph_path.name}.",
        "applied_action": mut.action,
    }


def create_session(graph_path: str | Path) -> SessionState:
    path = Path(graph_path).expanduser().resolve()
    return SessionState(graph=load_graph(path), graph_path=path)


def create_server(graph_path: str | Path, session: SessionState | None = None) -> Any:
    """Build a FastMCP server bound to one in-process playbook session."""
    try:
        from mcp.server.mcpserver import MCPServer
    except ImportError:
        try:
            from mcp.server.fastmcp import FastMCP as MCPServer
        except ImportError as exc:
            raise ImportError(
                "MCP is not installed. Install with: pip install 'procedural-graphs[mcp]'"
            ) from exc

    state = session or create_session(graph_path)
    server = MCPServer("procedural-graphs")

    @server.tool()
    def get_procedural_guidance(last_action: str | None = None) -> dict[str, Any]:
        """Localize from the in-memory session and return soft 1–2 hop guidance JSON."""
        if last_action:
            state.trajectory.append(
                TrajectoryStep(action=last_action, tool_name=last_action, status="reported")
            )
        block = _compile(state)
        payload = _block_to_json(block)
        payload["cursor"] = state.cursor
        return payload

    @server.tool()
    def advance_procedure(next_step_id: str, evidence: str = "") -> dict[str, Any]:
        """Move the playbook cursor along an outgoing edge; warn (do not crash) otherwise."""
        resolved = _resolve_node_id(state.graph, next_step_id) or next_step_id
        origin = state.cursor
        neighbors = _outgoing_targets(state.graph, origin)
        if resolved not in neighbors:
            block = _compile(state)
            return {
                "ok": False,
                "warning": (
                    f"{next_step_id!r} is not an outgoing neighbor of "
                    f"{origin!r}; cursor unchanged."
                ),
                "cursor": state.cursor,
                "guidance": _block_to_json(block),
            }
        state.cursor = resolved
        state.trajectory.append(
            TrajectoryStep(
                action=resolved,
                tool_name=resolved,
                observation=evidence or None,
                status="advanced",
            )
        )
        block = _compile(state)
        return {
            "ok": True,
            "cursor": state.cursor,
            "evidence": evidence,
            "guidance": _block_to_json(block),
        }

    @server.tool()
    def report_procedural_anomaly(issue_description: str) -> dict[str, Any]:
        """Record a failed trajectory; the host agent must propose apply_graph_mutation."""
        return report_anomaly(state, issue_description)

    @server.tool()
    def apply_graph_mutation(mutation: Any) -> dict[str, Any]:
        """Validate and persist one GraphMutation onto the active playbook YAML."""
        return apply_mutation(state, mutation)

    server.procedural_session = state  # type: ignore[attr-defined]
    return server


def run_server(graph_path: str | Path) -> None:
    create_server(graph_path).run()
