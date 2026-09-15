"""Console entry: ``procedural-graphs serve`` (optional ``--graph`` override)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="procedural-graphs",
        description="Procedural Graph SDK CLI (FastMCP overlay).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Run the FastMCP server using the central playbook hub.")
    serve.add_argument(
        "--graph",
        default=None,
        help=(
            "Optional path to a YAML or JSON playbook. "
            "When omitted, playbooks load from ~/.procedural-graphs/playbooks."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.command == "serve":
        from procedural_graphs.mcp_server import run_server
        from procedural_graphs.storage import ensure_central_hub_initialized

        ensure_central_hub_initialized()
        if args.graph is None:
            run_server()
            return
        graph = Path(args.graph)
        if not graph.is_file():
            print(f"Playbook not found: {graph}", file=sys.stderr)
            raise SystemExit(2)
        run_server(graph)


if __name__ == "__main__":
    main()
