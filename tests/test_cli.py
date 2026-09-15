"""CLI serve: --graph is optional; default is the central hub."""

from __future__ import annotations

from pathlib import Path

import pytest

from procedural_graphs.cli import build_parser, main


def test_serve_parser_accepts_missing_graph() -> None:
    args = build_parser().parse_args(["serve"])
    assert args.graph is None
    args = build_parser().parse_args(["serve", "--graph", "custom.yaml"])
    assert args.graph == "custom.yaml"


def test_serve_without_graph_calls_run_server(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    called: dict[str, object] = {}

    def fake_run(graph_path=None) -> None:
        called["graph_path"] = graph_path

    monkeypatch.setattr("procedural_graphs.mcp_server.run_server", fake_run)
    main(["serve"])
    assert called["graph_path"] is None


def test_serve_with_graph_override_requires_existing_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    missing = tmp_path / "nope.yaml"
    with pytest.raises(SystemExit) as exc:
        main(["serve", "--graph", str(missing)])
    assert exc.value.code == 2

    playbook = tmp_path / "custom.yaml"
    playbook.write_text("entry_id: Start\nnodes: []\nedges: []\n", encoding="utf-8")
    called: dict[str, object] = {}

    def fake_run(graph_path=None) -> None:
        called["graph_path"] = graph_path

    monkeypatch.setattr("procedural_graphs.mcp_server.run_server", fake_run)
    main(["serve", "--graph", str(playbook)])
    assert Path(called["graph_path"]) == playbook
