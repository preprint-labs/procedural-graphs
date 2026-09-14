"""Locate–extract–generate situational guidance (soft bias only)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from procedural_graphs.graph import ProceduralGraph
from procedural_graphs.localizer import NodeLocalizer, TrajectoryLike, _as_steps
from procedural_graphs.schema import GuidanceBlock as SchemaGuidanceBlock
from procedural_graphs.schema import ProcedureNode, TransitionEdge

LLMCallable = Callable[[str], str]

# Soft cap for the deterministic compiler (~200 tokens ≈ 800 chars).
_MAX_TEXT_CHARS = 800


class GuidanceBlock(SchemaGuidanceBlock):
    """Schema block plus the MCP/playbook alias ``valid_next``."""

    @property
    def valid_next(self) -> list[TransitionEdge]:
        return self.next_edges


class GuidanceEngine:
    """Deterministic compiler by default; optional generative ``llm_callable``."""

    def __init__(
        self,
        llm_callable: LLMCallable | None = None,
        *,
        hops: int = 2,
        window: int = 3,
        localizer: NodeLocalizer | None = None,
    ) -> None:
        self.llm_callable = llm_callable
        self.hops = hops
        self.window = window
        self.localizer = localizer or NodeLocalizer()

    def compile(
        self,
        graph: ProceduralGraph,
        trajectory: TrajectoryLike = None,
        *,
        query: str | None = None,
        active_node_id: str | None = None,
        hops: int | None = None,
    ) -> GuidanceBlock:
        hop_budget = self.hops if hops is None else hops
        node_id = active_node_id
        if node_id is None:
            node_id = self.localizer.locate(graph, trajectory)

        use_full = node_id is None or not graph.has_node(node_id)
        if use_full:
            view = graph
            current = None
            edges = list(graph.edges)
            notes = [
                "No localized node; compiling from the full graph (soft bias only).",
            ]
            preconditions: list[str] = []
        else:
            view = graph.neighborhood(node_id, hops=hop_budget)
            current = graph.get_node(node_id)
            edges = graph.outgoing(node_id)
            preconditions = list(current.preconditions or [])
            notes = _advisory_from_edges(edges)
            notes.append("Soft bias only: the solver is not forced to take an edge.")

        text = _compile_text(
            current=current,
            edges=edges,
            preconditions=preconditions,
            notes=notes,
            used_full_graph=use_full,
            view=view,
        )
        block = GuidanceBlock(
            text=text,
            current_procedure=current,
            preconditions=preconditions,
            next_edges=edges,
            advisory_notes=notes,
            hops=hop_budget,
            used_full_graph=use_full,
            active_node_id=None if use_full else node_id,
        )
        if self.llm_callable is not None:
            return self._with_llm(block, graph, trajectory, query, view)
        return block

    generate = compile

    def _with_llm(
        self,
        compiled: GuidanceBlock,
        graph: ProceduralGraph,
        trajectory: TrajectoryLike,
        query: str | None,
        view: ProceduralGraph,
    ) -> GuidanceBlock:
        prompt = _psi_prompt(compiled, graph, trajectory, query, view, self.window)
        raw = self.llm_callable(prompt)  # type: ignore[misc]
        body = (raw or "").strip()
        if not body:
            return compiled
        text = body if len(body) <= _MAX_TEXT_CHARS else body[: _MAX_TEXT_CHARS - 1] + "…"
        notes = list(compiled.advisory_notes)
        if "Soft bias only" not in " ".join(notes):
            notes.append("Soft bias only: the solver is not forced to take an edge.")
        return compiled.model_copy(update={"text": text, "advisory_notes": notes})


def _advisory_from_edges(edges: Sequence[TransitionEdge]) -> list[str]:
    notes: list[str] = []
    for edge in edges:
        if edge.guidance:
            notes.append(edge.guidance)
        if edge.pitfalls:
            notes.append(f"pitfall: {edge.pitfalls}")
    return notes


def _compile_text(
    *,
    current: ProcedureNode | None,
    edges: Sequence[TransitionEdge],
    preconditions: Sequence[str],
    notes: Sequence[str],
    used_full_graph: bool,
    view: ProceduralGraph,
) -> str:
    lines = ["[PROCEDURAL GUIDANCE]"]
    if used_full_graph:
        lines.append("Scope: full graph (unmatched / no active node).")
        names = [n.name for n in view.nodes.values()]
        if names:
            lines.append("Nodes: " + ", ".join(names[:12]))
    elif current is not None:
        lines.append(f"Current: {current.name}")
        if current.description:
            lines.append(current.description)
    if preconditions:
        lines.append("Preconditions: " + "; ".join(preconditions))
    if edges:
        lines.append("Valid next (soft):")
        for edge in edges:
            cond = edge.condition or "(none)"
            extra = edge.guidance or ""
            lines.append(f"- {edge.source} -> {edge.target} if {cond}" + (f" | {extra}" if extra else ""))
    if notes:
        lines.append("Advisory: " + "; ".join(notes[:6]))
    text = "\n".join(lines)
    if len(text) > _MAX_TEXT_CHARS:
        text = text[: _MAX_TEXT_CHARS - 1] + "…"
    return text


def _psi_prompt(
    compiled: GuidanceBlock,
    graph: ProceduralGraph,
    trajectory: TrajectoryLike,
    query: str | None,
    view: ProceduralGraph,
    window: int,
) -> str:
    steps = _as_steps(trajectory)[-window:]
    recent = []
    for step in steps:
        label = step.action or step.tool_name or "?"
        recent.append(label)
    return (
        "Write short situational procedural guidance (soft bias; do not dictate the next tool).\n"
        f"Query: {query or ''}\n"
        f"Recent steps: {recent}\n"
        f"Subgraph nodes: {[n.name for n in view.nodes.values()]}\n"
        f"Compiled:\n{compiled.text}\n"
    )
