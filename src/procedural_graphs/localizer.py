"""Online node localization from a trajectory (paper locate rules)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from procedural_graphs.graph import ProceduralGraph
from procedural_graphs.schema import TrajectoryRecord, TrajectoryStep

TrajectoryLike = (
    TrajectoryRecord
    | Sequence[TrajectoryStep | dict[str, Any] | str]
    | None
)


def _as_steps(trajectory: TrajectoryLike) -> list[TrajectoryStep]:
    if trajectory is None:
        return []
    if isinstance(trajectory, TrajectoryRecord):
        return list(trajectory.steps)
    steps: list[TrajectoryStep] = []
    for item in trajectory:
        if isinstance(item, TrajectoryStep):
            steps.append(item)
        elif isinstance(item, str):
            steps.append(TrajectoryStep(action=item, tool_name=item))
        else:
            steps.append(TrajectoryStep.model_validate(item))
    return steps


def _step_keys(step: TrajectoryStep) -> list[str]:
    keys: list[str] = []
    for raw in (step.action, step.tool_name):
        if raw and raw not in keys:
            keys.append(raw)
    return keys


class NodeLocalizer:
    """Exact-match last procedure to a node; empty trajectory → Start."""

    def locate(
        self,
        graph: ProceduralGraph,
        trajectory: TrajectoryLike,
        k: int = 1,
    ) -> str | None:
        steps = _as_steps(trajectory)
        if not steps:
            return graph.start_id()

        last = steps[-1]
        matched = self._match_step(graph, last)
        if matched is not None:
            return matched

        window = max(int(k), 0)
        if window <= 0:
            return None
        for step in reversed(steps[-window:]):
            matched = self._match_step(graph, step)
            if matched is not None:
                return matched
        return None

    @staticmethod
    def _match_step(graph: ProceduralGraph, step: TrajectoryStep) -> str | None:
        for key in _step_keys(step):
            found = graph.find_node(key)
            if found is not None:
                return found.id
        return None
