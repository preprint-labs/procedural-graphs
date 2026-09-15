"""FastMCP overlay: soft playbook guidance over hub-scoped ProceduralGraph sessions."""

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
from procedural_graphs.storage import (
    ensure_central_hub_initialized,
    get_playbook_path,
    list_central_playbooks,
    load_state_cache,
    save_state_cache,
)

TOOL_NAMES = (
    "list_available_playbooks",
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
    playbook: str = "feature-dev"
    task_id: str = "default"
    repo: str = ""

    def __post_init__(self) -> None:
        if self.cursor is None:
            self.cursor = self.graph.start_id()
        if self.evolver is None:
            # Rejection memory only; llm_callable is never invoked by MCP tools.
            self.evolver = GraphEvolver(llm_callable=lambda _prompt: "")


class PlaybookSessionHub:
    """In-memory sessions keyed by repo, task_id, and playbook; cursor cache on disk."""

    def __init__(
        self,
        graph_override: str | Path | None = None,
        repo: str | None = None,
    ) -> None:
        ensure_central_hub_initialized()
        self.graph_override = (
            Path(graph_override).expanduser().resolve() if graph_override is not None else None
        )
        self.repo = repo if repo is not None else str(Path.cwd().resolve())
        self._sessions: dict[str, SessionState] = {}
        self._task_playbook: dict[str, str] = {}

    def resolve_path(self, playbook: str) -> Path:
        if self.graph_override is not None and playbook in {
            "feature-dev",
            self.graph_override.stem,
        }:
            return self.graph_override
        return get_playbook_path(playbook)

    def session_key(self, task_id: str, playbook: str) -> str:
        return f"{self.repo}::{task_id}::{playbook}"

    def remember_playbook(self, task_id: str, playbook: str) -> None:
        self._task_playbook[f"{self.repo}::{task_id}"] = playbook

    def playbook_for_task(self, task_id: str, playbook: str | None) -> str:
        if playbook:
            return playbook
        return self._task_playbook.get(f"{self.repo}::{task_id}", "feature-dev")

    def get_session(self, playbook: str = "feature-dev", task_id: str = "default") -> SessionState:
        key = self.session_key(task_id, playbook)
        existing = self._sessions.get(key)
        if existing is not None:
            return existing
        path = self.resolve_path(playbook)
        session = SessionState(
            graph=load_graph(path),
            graph_path=path,
            playbook=playbook,
            task_id=task_id,
            repo=self.repo,
        )
        cached = load_state_cache().get("sessions", {}).get(key)
        if isinstance(cached, dict):
            cursor = cached.get("cursor")
            if isinstance(cursor, str) and session.graph.has_node(cursor):
                session.cursor = cursor
            raw_steps = cached.get("trajectory") or []
            if isinstance(raw_steps, list):
                session.trajectory = [TrajectoryStep.model_validate(step) for step in raw_steps]
        self._sessions[key] = session
        self.remember_playbook(task_id, playbook)
        return session

    def persist_session(self, session: SessionState) -> None:
        cache = load_state_cache()
        key = self.session_key(session.task_id, session.playbook)
        cache.setdefault("sessions", {})[key] = {
            "repo": session.repo,
            "task_id": session.task_id,
            "playbook": session.playbook,
            "cursor": session.cursor,
            "graph_path": str(session.graph_path),
            "trajectory": [step.model_dump() for step in session.trajectory],
        }
        save_state_cache(cache)

    def advance_procedure(
        self,
        next_step_id: str,
        task_id: str = "default",
        playbook: str | None = None,
        evidence: str = "",
    ) -> dict[str, Any]:
        resolved_playbook = self.playbook_for_task(task_id, playbook)
        session = self.get_session(playbook=resolved_playbook, task_id=task_id)
        result = advance_cursor(session, next_step_id, evidence)
        self.persist_session(session)
        return result

    def sync_graph(self, path: Path, graph: ProceduralGraph) -> None:
        resolved = path.resolve()
        for session in self._sessions.values():
            if session.graph_path.resolve() == resolved:
                session.graph = graph
                if session.cursor and not session.graph.has_node(session.cursor):
                    session.cursor = session.graph.start_id()


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


def advance_cursor(session: SessionState, next_step_id: str, evidence: str = "") -> dict[str, Any]:
    """Move the playbook cursor along an outgoing edge; warn (do not crash) otherwise."""
    resolved = _resolve_node_id(session.graph, next_step_id) or next_step_id
    origin = session.cursor
    neighbors = _outgoing_targets(session.graph, origin)
    if resolved not in neighbors:
        block = _compile(session)
        return {
            "ok": False,
            "warning": (
                f"{next_step_id!r} is not an outgoing neighbor of "
                f"{origin!r}; cursor unchanged."
            ),
            "cursor": session.cursor,
            "guidance": _block_to_json(block),
        }
    session.cursor = resolved
    session.trajectory.append(
        TrajectoryStep(
            action=resolved,
            tool_name=resolved,
            observation=evidence or None,
            status="advanced",
        )
    )
    block = _compile(session)
    return {
        "ok": True,
        "cursor": session.cursor,
        "evidence": evidence,
        "guidance": _block_to_json(block),
    }


def list_available_playbooks() -> list[str]:
    """Return hub playbook stems (e.g. feature-dev, bugfix)."""
    return list_central_playbooks()


def guidance_for(
    hub: PlaybookSessionHub,
    last_action: str | None = None,
    playbook: str = "feature-dev",
    task_id: str = "default",
) -> dict[str, Any]:
    session = hub.get_session(playbook=playbook, task_id=task_id)
    hub.remember_playbook(task_id, playbook)
    if last_action:
        session.trajectory.append(
            TrajectoryStep(action=last_action, tool_name=last_action, status="reported")
        )
    block = _compile(session)
    payload = _block_to_json(block)
    payload["cursor"] = session.cursor
    payload["playbook"] = playbook
    payload["task_id"] = task_id
    hub.persist_session(session)
    return payload


def apply_hub_mutation(
    hub: PlaybookSessionHub,
    mutation: Any,
    playbook: str = "feature-dev",
) -> dict[str, Any]:
    path = hub.resolve_path(playbook)
    scratch = SessionState(graph=load_graph(path), graph_path=path, playbook=playbook)
    result = apply_mutation(scratch, mutation)
    if result.get("success"):
        hub.sync_graph(path, scratch.graph)
    return result


def create_session(
    graph_path: str | Path | None = None,
    playbook: str = "feature-dev",
) -> SessionState:
    if graph_path is not None:
        path = Path(graph_path).expanduser().resolve()
    else:
        path = get_playbook_path(playbook)
    return SessionState(graph=load_graph(path), graph_path=path, playbook=playbook)


def create_server(graph_path: str | Path | None = None, session: SessionState | None = None) -> Any:
    """Build a FastMCP server bound to the central hub (optional path override)."""
    try:
        from mcp.server.mcpserver import MCPServer
    except ImportError:
        try:
            from mcp.server.fastmcp import FastMCP as MCPServer
        except ImportError as exc:
            raise ImportError(
                "MCP is not installed. Install with: pip install 'procedural-graphs[mcp]'"
            ) from exc

    ensure_central_hub_initialized()
    hub = PlaybookSessionHub(graph_override=graph_path)
    if session is not None:
        hub._sessions[hub.session_key(session.task_id, session.playbook)] = session

    server = MCPServer("procedural-graphs")

    @server.tool()
    def list_available_playbooks() -> list[str]:
        """List playbook stems in the central hub (~/.procedural-graphs/playbooks)."""
        return list_central_playbooks()

    @server.tool()
    def get_procedural_guidance(
        last_action: str | None = None,
        playbook: str = "feature-dev",
        task_id: str = "default",
    ) -> dict[str, Any]:
        """Localize from the task-scoped session and return soft 1–2 hop guidance JSON."""
        return guidance_for(hub, last_action=last_action, playbook=playbook, task_id=task_id)

    @server.tool()
    def advance_procedure(
        next_step_id: str,
        evidence: str = "",
        task_id: str = "default",
        playbook: str = "",
    ) -> dict[str, Any]:
        """Move the playbook cursor along an outgoing edge; warn (do not crash) otherwise."""
        return hub.advance_procedure(
            next_step_id,
            task_id=task_id,
            playbook=playbook or None,
            evidence=evidence,
        )

    @server.tool()
    def report_procedural_anomaly(
        issue_description: str,
        task_id: str = "default",
        playbook: str = "",
    ) -> dict[str, Any]:
        """Record a failed trajectory; the host agent must propose apply_graph_mutation."""
        resolved = hub.playbook_for_task(task_id, playbook or None)
        return report_anomaly(hub.get_session(playbook=resolved, task_id=task_id), issue_description)

    @server.tool()
    def apply_graph_mutation(mutation: Any, playbook: str = "feature-dev") -> dict[str, Any]:
        """Validate and persist one GraphMutation onto the central hub playbook YAML."""
        return apply_hub_mutation(hub, mutation, playbook=playbook)

    server.procedural_hub = hub  # type: ignore[attr-defined]
    server.procedural_session = session or hub.get_session()  # type: ignore[attr-defined]
    return server


def run_server(graph_path: str | Path | None = None) -> None:
    ensure_central_hub_initialized()
    create_server(graph_path).run()
