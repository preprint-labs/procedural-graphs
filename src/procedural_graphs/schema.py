"""Pydantic models aligned with the Procedural Graph paper (arXiv:2609.09153)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

NodeKind = Literal["tool", "skill", "reasoning", "status"]
RelationType = Literal["sequential", "conditional", "fallback"]
MutationAction = Literal["add_node", "delete_node", "add_edge", "delete_edge"]


class ProcedureNode(BaseModel):
    id: str
    name: str
    description: str = ""
    allowed_tools: list[str] | None = None
    preconditions: list[str] | None = None
    postconditions: list[str] | None = None
    kind: NodeKind | None = None
    terminal: bool = False


class TransitionEdge(BaseModel):
    source: str
    target: str
    relation: str = "LEADS_TO"
    condition: str = ""
    guidance: str = ""
    pitfalls: str = ""
    relation_type: RelationType | None = None


class GraphMutation(BaseModel):
    action: MutationAction
    data: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""


class TrajectoryStep(BaseModel):
    tool_name: str | None = None
    action: str | None = None
    args: dict[str, Any] | None = None
    output: Any = None
    observation: Any = None
    status: str | None = None


class TrajectoryRecord(BaseModel):
    steps: list[TrajectoryStep] = Field(default_factory=list)
    final_success: bool | None = None
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    query: str | None = None


class RejectionRecord(BaseModel):
    mutations: list[GraphMutation] = Field(default_factory=list)
    validation_score: float | None = None
    trajectory_summary: str = ""


class GuidanceBlock(BaseModel):
    text: str
    current_procedure: ProcedureNode | None = None
    preconditions: list[str] = Field(default_factory=list)
    next_edges: list[TransitionEdge] = Field(default_factory=list)
    advisory_notes: list[str] = Field(default_factory=list)
    hops: int = 2
    used_full_graph: bool = False
    active_node_id: str | None = None
