"""Offline graph evolution (paper §3.3): LLM edits gated by structure and score."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from typing import Any

from procedural_graphs.graph import ProceduralGraph, StructuralValidationError
from procedural_graphs.guidance import GuidanceEngine
from procedural_graphs.localizer import NodeLocalizer
from procedural_graphs.schema import GraphMutation, RejectionRecord, TrajectoryRecord

LLMCallable = Callable[[str], str]
Validator = Callable[[ProceduralGraph], float]


def _trace_score(record: TrajectoryRecord) -> float | None:
    if record.score is not None:
        return record.score
    if record.final_success is True:
        return 1.0
    if record.final_success is False:
        return 0.0
    return None


def partition_traces(
    records: Sequence[TrajectoryRecord],
    *,
    score_threshold: float = 0.5,
) -> tuple[list[TrajectoryRecord], list[TrajectoryRecord]]:
    """Split traces into high- vs low-scoring groups (score, else final_success)."""
    high: list[TrajectoryRecord] = []
    low: list[TrajectoryRecord] = []
    for rec in records:
        score = _trace_score(rec)
        if rec.final_success is True:
            high.append(rec)
            continue
        if rec.final_success is False:
            low.append(rec)
            continue
        if score is None:
            continue
        if score >= score_threshold:
            high.append(rec)
        else:
            low.append(rec)
    return high, low


def _canonical_mutation(mut: GraphMutation) -> tuple[str, str]:
    return (mut.action, json.dumps(mut.data, sort_keys=True, default=str))


def canonical_mutation_set(mutations: Sequence[GraphMutation]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted(_canonical_mutation(m) for m in mutations))


def mutations_equivalent(
    left: Sequence[GraphMutation],
    right: Sequence[GraphMutation],
) -> bool:
    return canonical_mutation_set(left) == canonical_mutation_set(right)


def parse_mutations(raw: str) -> list[GraphMutation]:
    """Parse an LLM string into GraphMutation models (JSON list or {mutations: [...]})."""
    text = raw.strip()
    if not text:
        return []
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, flags=re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    try:
        payload: Any = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"(\[.*\]|\{.*\})", text, flags=re.DOTALL)
        if not match:
            return []
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            return []
    if isinstance(payload, dict):
        payload = payload.get("mutations", payload.get("edits", []))
    if not isinstance(payload, list):
        return []
    return [GraphMutation.model_validate(item) for item in payload]


def _summarize_records(records: Sequence[TrajectoryRecord], limit: int = 4) -> str:
    parts: list[str] = []
    for rec in records[:limit]:
        actions = []
        for step in rec.steps:
            label = step.tool_name or step.action or "?"
            actions.append(label)
        score = _trace_score(rec)
        score_s = f"{score:.2f}" if score is not None else "?"
        parts.append(f"success={rec.final_success} score={score_s} path={' > '.join(actions) or '(empty)'}")
    return "; ".join(parts)


class GraphEvolver:
    """Contrast high/low traces, propose Add/Delete edits, commit only if the gate passes."""

    def __init__(
        self,
        llm_callable: LLMCallable,
        validator: Validator | None = None,
        *,
        score_threshold: float = 0.5,
    ) -> None:
        self.llm_callable = llm_callable
        self.validator = validator
        self.score_threshold = score_threshold
        self.rejection_memory: list[RejectionRecord] = []
        # Imported so a sibling localizer/guidance implementation is part of this package surface.
        self._localizer = NodeLocalizer
        self._guidance = GuidanceEngine

    def evolve(
        self,
        graph: ProceduralGraph,
        records: Sequence[TrajectoryRecord],
    ) -> ProceduralGraph:
        high, low = partition_traces(records, score_threshold=self.score_threshold)
        prompt = self._build_prompt(graph, high, low)
        raw = self.llm_callable(prompt)
        mutations = parse_mutations(raw)
        if not mutations:
            return graph
        if self._is_rejected(mutations):
            return graph

        try:
            candidate = graph.apply_mutations(mutations, inplace=False)
        except (KeyError, ValueError, StructuralValidationError):
            self._remember(mutations, validation_score=0.0, records=records)
            return graph

        ok_cand, _errors = candidate.validate_structure()
        if not ok_cand:
            self._remember(mutations, validation_score=0.0, records=records)
            return graph

        score_prev, score_cand = self._scores(graph, candidate)
        if score_cand >= score_prev:
            return candidate

        self._remember(mutations, validation_score=score_cand, records=records)
        return graph

    def _scores(self, previous: ProceduralGraph, candidate: ProceduralGraph) -> tuple[float, float]:
        if self.validator is None:
            ok_prev, _ = previous.validate_structure()
            return (1.0 if ok_prev else 0.0, 1.0)
        return float(self.validator(previous)), float(self.validator(candidate))

    def _is_rejected(self, mutations: Sequence[GraphMutation]) -> bool:
        for record in self.rejection_memory:
            if mutations_equivalent(mutations, record.mutations):
                return True
        return False

    def _remember(
        self,
        mutations: Sequence[GraphMutation],
        *,
        validation_score: float | None,
        records: Sequence[TrajectoryRecord],
    ) -> None:
        self.rejection_memory.append(
            RejectionRecord(
                mutations=list(mutations),
                validation_score=validation_score,
                trajectory_summary=_summarize_records(records),
            )
        )

    def _build_prompt(
        self,
        graph: ProceduralGraph,
        high: Sequence[TrajectoryRecord],
        low: Sequence[TrajectoryRecord],
    ) -> str:
        payload = {
            "task": (
                "Contrast high-scoring vs low-scoring traces and propose graph edits. "
                "Return a JSON list of GraphMutation objects. "
                "Actions: add_node, delete_node, add_edge, delete_edge. "
                "Attribute updates are delete_edge then add_edge. "
                "Do not repeat rejected edits."
            ),
            "graph": graph.serialize(),
            "high_traces": [r.model_dump() for r in high],
            "low_traces": [r.model_dump() for r in low],
            "rejection_memory": [r.model_dump() for r in self.rejection_memory],
        }
        return json.dumps(payload, default=str)
