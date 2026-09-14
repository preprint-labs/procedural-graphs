"""Framework-agnostic agent wrapper: localize, inject guidance, record, optionally evolve."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from procedural_graphs.evolver import GraphEvolver
from procedural_graphs.graph import ProceduralGraph
from procedural_graphs.guidance import GuidanceEngine
from procedural_graphs.localizer import NodeLocalizer
from procedural_graphs.schema import TrajectoryRecord, TrajectoryStep

AgentFn = Callable[[str, list[TrajectoryStep], str], Any]


def _as_steps(history: Sequence[Any] | None) -> list[TrajectoryStep]:
    if not history:
        return []
    steps: list[TrajectoryStep] = []
    for item in history:
        if isinstance(item, TrajectoryStep):
            steps.append(item)
        elif isinstance(item, dict):
            steps.append(TrajectoryStep.model_validate(item))
        else:
            steps.append(TrajectoryStep(action=str(item), tool_name=str(item)))
    return steps


def _coerce_step(result: Any) -> TrajectoryStep:
    if isinstance(result, TrajectoryStep):
        return result
    if isinstance(result, dict):
        data = dict(result)
        if "tool_name" not in data and "action" in data:
            data["tool_name"] = data.get("action")
        if "action" not in data and "tool_name" in data:
            data["action"] = data.get("tool_name")
        known = {
            "tool_name",
            "action",
            "args",
            "output",
            "observation",
            "status",
        }
        return TrajectoryStep.model_validate({k: data[k] for k in known if k in data})
    if result is None:
        return TrajectoryStep()
    text = str(result)
    return TrajectoryStep(action=text, tool_name=text, output=result)


def _episode_flags(result: Any) -> tuple[bool | None, float | None, bool]:
    """Return (final_success, score, done) from an agent_fn result."""
    if not isinstance(result, dict):
        return None, None, False
    done = bool(result.get("done") or result.get("finished") or result.get("stop"))
    success = result.get("final_success")
    if success is None and "success" in result:
        success = result.get("success")
    score = result.get("score")
    if score is not None:
        score = float(score)
    if success is not None:
        success = bool(success)
        done = True
    return success, score, done


def _guidance_text(block: Any) -> str:
    if block is None:
        return ""
    if isinstance(block, str):
        return block
    text = getattr(block, "text", None)
    if text is not None:
        return str(text)
    return str(block)


class GuidedAgent:
    """Each step: localize → guidance text → agent_fn(query, history, guidance)."""

    def __init__(
        self,
        agent_fn: AgentFn,
        graph: ProceduralGraph,
        evolve: bool = False,
        *,
        evolver: GraphEvolver | None = None,
        llm_callable: Callable[[str], str] | None = None,
        validator: Callable[[ProceduralGraph], float] | None = None,
        localizer: NodeLocalizer | None = None,
        guidance_engine: GuidanceEngine | None = None,
    ) -> None:
        self.agent_fn = agent_fn
        self.graph = graph
        self.evolve = evolve
        self.evolver = evolver
        if self.evolver is None and llm_callable is not None:
            self.evolver = GraphEvolver(llm_callable, validator=validator)
        self.localizer = localizer if localizer is not None else NodeLocalizer()
        self.guidance_engine = guidance_engine if guidance_engine is not None else GuidanceEngine()
        self.records: list[TrajectoryRecord] = []
        self.current: TrajectoryRecord | None = None

    @property
    def history(self) -> list[TrajectoryStep]:
        if self.current is None:
            return []
        return self.current.steps

    def reset(self, query: str | None = None) -> TrajectoryRecord:
        self.current = TrajectoryRecord(query=query, steps=[])
        return self.current

    def step(self, query: str, history: Sequence[Any] | None = None) -> Any:
        if self.current is None or (self.current.query is None and query):
            self.reset(query)
        elif self.current.query is None:
            self.current.query = query

        steps = _as_steps(history) if history is not None else list(self.current.steps)
        node_id = self._locate(steps)
        guidance = self._compile_guidance(query, steps, node_id)
        result = self.agent_fn(query, steps, guidance)
        self.current.steps.append(_coerce_step(result))
        return result

    def finish(
        self,
        *,
        final_success: bool | None = None,
        score: float | None = None,
    ) -> TrajectoryRecord:
        rec = self.current or TrajectoryRecord()
        if final_success is not None:
            rec.final_success = final_success
        if score is not None:
            rec.score = score
        self.records.append(rec)
        if self.evolve and self.evolver is not None:
            self.graph = self.evolver.evolve(self.graph, [rec])
        self.current = None
        return rec

    def run(self, query: str, max_steps: int = 8) -> TrajectoryRecord:
        self.reset(query)
        success: bool | None = None
        score: float | None = None
        for _ in range(max_steps):
            result = self.step(query)
            success, score, done = _episode_flags(result)
            if done:
                break
        return self.finish(final_success=success, score=score)

    def _locate(self, steps: list[TrajectoryStep]) -> str | None:
        locate = self.localizer.locate
        try:
            return locate(self.graph, steps, k=1)
        except TypeError:
            return locate(self.graph, steps)

    def _compile_guidance(self, query: str, steps: list[TrajectoryStep], node_id: str | None) -> str:
        eng = self.guidance_engine
        compile_fn = (
            getattr(eng, "compile", None)
            or getattr(eng, "generate", None)
            or getattr(eng, "guide", None)
        )
        if compile_fn is None:
            raise TypeError("guidance engine must define compile, generate, or guide")
        try:
            block = compile_fn(
                self.graph,
                trajectory=steps,
                query=query,
                active_node_id=node_id,
            )
        except TypeError:
            try:
                block = compile_fn(self.graph, steps, query)
            except TypeError:
                block = compile_fn(self.graph, node_id)
        return _guidance_text(block)
