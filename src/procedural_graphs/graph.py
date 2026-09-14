"""NetworkX-backed attributed procedural graph \(\mathcal{G}=(V,R,E,\Phi)\)."""

from __future__ import annotations

import copy
from typing import Any, Iterable

import networkx as nx

from procedural_graphs.schema import GraphMutation, ProcedureNode, TransitionEdge


class StructuralValidationError(ValueError):
    """Raised when a candidate graph fails paper §3.3 structural checks."""


class ProceduralGraph:
    """Directed multigraph of procedures and attributed transitions."""

    def __init__(self, entry_id: str | None = None) -> None:
        self._g = nx.MultiDiGraph()
        self.entry_id = entry_id

    def __len__(self) -> int:
        return self._g.number_of_nodes()

    @property
    def nodes(self) -> dict[str, ProcedureNode]:
        return {nid: ProcedureNode.model_validate(data["spec"]) for nid, data in self._g.nodes(data=True)}

    @property
    def edges(self) -> list[TransitionEdge]:
        out: list[TransitionEdge] = []
        for u, v, _key, data in self._g.edges(keys=True, data=True):
            out.append(TransitionEdge.model_validate(data["spec"]))
        return out

    def get_node(self, node_id: str) -> ProcedureNode:
        return ProcedureNode.model_validate(self._g.nodes[node_id]["spec"])

    def has_node(self, node_id: str) -> bool:
        return self._g.has_node(node_id)

    def find_node(self, key: str) -> ProcedureNode | None:
        if self._g.has_node(key):
            return self.get_node(key)
        lowered = key.lower()
        for nid, data in self._g.nodes(data=True):
            spec = ProcedureNode.model_validate(data["spec"])
            if spec.name.lower() == lowered:
                return spec
        return None

    def start_id(self) -> str | None:
        if self.entry_id and self._g.has_node(self.entry_id):
            return self.entry_id
        if self._g.has_node("Start"):
            return "Start"
        for nid, data in self._g.nodes(data=True):
            spec = ProcedureNode.model_validate(data["spec"])
            if spec.name == "Start":
                return spec.id
        if self._g.number_of_nodes() == 0:
            return None
        return next(iter(self._g.nodes()))

    def add_procedure(self, node: ProcedureNode | dict[str, Any]) -> None:
        spec = ProcedureNode.model_validate(node)
        self._g.add_node(spec.id, spec=spec.model_dump())
        if self.entry_id is None and (spec.id == "Start" or spec.name == "Start"):
            self.entry_id = spec.id

    def add_transition(self, edge: TransitionEdge | dict[str, Any]) -> None:
        spec = TransitionEdge.model_validate(edge)
        if not self._g.has_node(spec.source) or not self._g.has_node(spec.target):
            missing = spec.source if not self._g.has_node(spec.source) else spec.target
            raise KeyError(f"Cannot add edge; missing node {missing!r}")
        self._g.add_edge(spec.source, spec.target, key=spec.relation, spec=spec.model_dump())

    def outgoing(self, node_id: str) -> list[TransitionEdge]:
        if not self._g.has_node(node_id):
            return []
        edges: list[TransitionEdge] = []
        for _u, _v, _key, data in self._g.out_edges(node_id, keys=True, data=True):
            edges.append(TransitionEdge.model_validate(data["spec"]))
        return edges

    def is_terminal(self, node_id: str) -> bool:
        spec = self.get_node(node_id)
        if spec.terminal:
            return True
        return self._g.out_degree(node_id) == 0

    def copy(self) -> ProceduralGraph:
        clone = ProceduralGraph(entry_id=self.entry_id)
        clone._g = copy.deepcopy(self._g)
        return clone

    def apply_mutations(
        self,
        mutations: Iterable[GraphMutation | dict[str, Any]],
        *,
        inplace: bool = False,
    ) -> ProceduralGraph:
        """Apply Add/Delete node/edge mutations. Attribute updates are delete + re-add."""
        target = self if inplace else self.copy()
        for raw in mutations:
            mut = GraphMutation.model_validate(raw)
            target._apply_one(mut)
        return target

    def _apply_one(self, mut: GraphMutation) -> None:
        data = mut.data
        if mut.action == "add_node":
            self.add_procedure(data)
        elif mut.action == "delete_node":
            nid = data.get("id") or data.get("node_id")
            if nid and self._g.has_node(nid):
                self._g.remove_node(nid)
                if self.entry_id == nid:
                    self.entry_id = None
        elif mut.action == "add_edge":
            self.add_transition(data)
        elif mut.action == "delete_edge":
            source = data.get("source")
            target = data.get("target")
            relation = data.get("relation")
            if source is None or target is None or not self._g.has_edge(source, target):
                return
            if relation is not None and self._g.has_edge(source, target, key=relation):
                self._g.remove_edge(source, target, key=relation)
            else:
                keys = list(self._g[source][target].keys())
                if keys:
                    self._g.remove_edge(source, target, key=keys[0])

    def neighborhood(self, node_id: str, hops: int = 2) -> ProceduralGraph:
        """Outgoing h-hop neighborhood (paper default h=2)."""
        if not self._g.has_node(node_id):
            return ProceduralGraph(entry_id=self.entry_id)
        reached: set[str] = {node_id}
        frontier = {node_id}
        for _ in range(hops):
            nxt: set[str] = set()
            for u in frontier:
                nxt.update(self._g.successors(u))
            nxt -= reached
            if not nxt:
                break
            reached |= nxt
            frontier = nxt
        sub = ProceduralGraph(entry_id=node_id if node_id == self.start_id() else self.entry_id)
        for nid in reached:
            sub.add_procedure(self.get_node(nid))
        for edge in self.edges:
            if edge.source in reached and edge.target in reached:
                # keep only outgoing-reachable structure among visited nodes
                sub.add_transition(edge)
        return sub

    def serialize(self) -> dict[str, Any]:
        return {
            "entry_id": self.start_id(),
            "nodes": [n.model_dump() for n in self.nodes.values()],
            "edges": [e.model_dump() for e in self.edges],
        }

    @classmethod
    def load(cls, payload: dict[str, Any]) -> ProceduralGraph:
        graph = cls(entry_id=payload.get("entry_id") or payload.get("start") or payload.get("start_id"))
        nodes = payload.get("nodes") or payload.get("procedures") or []
        for node in nodes:
            graph.add_procedure(node)
        for edge in payload.get("edges") or payload.get("transitions") or []:
            graph.add_transition(edge)
        return graph

    def terminals(self) -> list[str]:
        return [nid for nid in self._g.nodes if self.is_terminal(nid)]

    def validate_structure(self) -> tuple[bool, list[str]]:
        """Paper §3.3 Step 3: Start, reachability to a terminal, no orphan components."""
        errors: list[str] = []
        if self._g.number_of_nodes() == 0:
            errors.append("graph is empty")
            return False, errors

        start = None
        if self.entry_id and self._g.has_node(self.entry_id):
            start = self.entry_id
        elif self._g.has_node("Start"):
            start = "Start"
        else:
            named = [nid for nid, data in self._g.nodes(data=True) if data["spec"].get("name") == "Start"]
            if named:
                start = named[0]
        if start is None:
            errors.append("missing designated Start node")

        terminals = self.terminals()
        if not terminals:
            errors.append("no terminal node (mark terminal=True or leave a sink)")

        if start is not None:
            undirected = self._g.to_undirected()
            components = list(nx.connected_components(undirected))
            if len(components) > 1:
                start_comp = next(c for c in components if start in c)
                orphans = [sorted(c) for c in components if c is not start_comp]
                if orphans:
                    errors.append(f"orphan isolated components: {orphans}")

        for nid in self._g.nodes:
            if self.is_terminal(nid):
                continue
            if self._g.out_degree(nid) == 0:
                errors.append(f"non-terminal {nid!r} has no out-edge")
                continue
            if terminals:
                reachable = nx.descendants(self._g, nid) | {nid}
                if not reachable.intersection(terminals):
                    errors.append(f"non-terminal {nid!r} cannot reach a terminal")

        return (len(errors) == 0), errors

    def assert_valid(self) -> None:
        ok, errors = self.validate_structure()
        if not ok:
            raise StructuralValidationError("; ".join(errors))

    def has_cycles(self) -> bool:
        return not nx.is_directed_acyclic_graph(self._g)

    def repair_cycles(self) -> ProceduralGraph:
        """Optional paper hook: drop one back-edge per simple cycle on a copy."""
        repaired = self.copy()
        try:
            cycles = nx.simple_cycles(repaired._g)
            seen: set[tuple[str, str, str]] = set()
            for cycle in cycles:
                if len(cycle) < 2:
                    continue
                u, v = cycle[-1], cycle[0]
                if not repaired._g.has_edge(u, v):
                    continue
                keys = list(repaired._g[u][v].keys())
                key = keys[0]
                ident = (u, v, str(key))
                if ident in seen:
                    continue
                repaired._g.remove_edge(u, v, key=key)
                seen.add(ident)
                if nx.is_directed_acyclic_graph(repaired._g):
                    break
        except nx.NetworkXNoCycle:
            pass
        return repaired
