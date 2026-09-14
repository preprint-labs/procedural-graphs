"""YAML and JSON playbook load/save for ProceduralGraph."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from procedural_graphs.graph import ProceduralGraph

_YAML_SUFFIXES = {".yaml", ".yml"}
_JSON_SUFFIXES = {".json"}


def load_graph(path: str | Path) -> ProceduralGraph:
    """Load a playbook from YAML or JSON, inferred from the file suffix."""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix in _JSON_SUFFIXES:
        return load_json(p)
    if suffix in _YAML_SUFFIXES:
        return load_yaml(p)
    raise ValueError(f"Unsupported playbook suffix {p.suffix!r}; use .yaml, .yml, or .json")


def save_graph(graph: ProceduralGraph, path: str | Path) -> None:
    """Write a playbook as YAML or JSON, inferred from the file suffix."""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix in _JSON_SUFFIXES:
        save_json(graph, p)
        return
    if suffix in _YAML_SUFFIXES:
        save_yaml(graph, p)
        return
    raise ValueError(f"Unsupported playbook suffix {p.suffix!r}; use .yaml, .yml, or .json")


def load_yaml(path: str | Path) -> ProceduralGraph:
    text = Path(path).read_text(encoding="utf-8")
    return loads_yaml(text)


def save_yaml(graph: ProceduralGraph, path: str | Path) -> None:
    Path(path).write_text(dumps_yaml(graph), encoding="utf-8")


def loads_yaml(text: str) -> ProceduralGraph:
    payload = yaml.safe_load(text)
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise TypeError("YAML playbook must be a mapping with nodes and edges")
    return ProceduralGraph.load(payload)


def dumps_yaml(graph: ProceduralGraph) -> str:
    return yaml.safe_dump(_playbook_payload(graph), sort_keys=False, allow_unicode=True)


def load_json(path: str | Path) -> ProceduralGraph:
    text = Path(path).read_text(encoding="utf-8")
    return loads_json(text)


def save_json(graph: ProceduralGraph, path: str | Path) -> None:
    Path(path).write_text(dumps_json(graph), encoding="utf-8")


def loads_json(text: str) -> ProceduralGraph:
    payload: Any = json.loads(text)
    if not isinstance(payload, dict):
        raise TypeError("JSON playbook must be an object with nodes and edges")
    return ProceduralGraph.load(payload)


def dumps_json(graph: ProceduralGraph, *, indent: int = 2) -> str:
    return json.dumps(_playbook_payload(graph), indent=indent) + "\n"


def _playbook_payload(graph: ProceduralGraph) -> dict[str, Any]:
    return graph.serialize()
