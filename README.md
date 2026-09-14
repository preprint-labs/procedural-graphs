# procedural-graphs 🧭

Python implementation of **Procedural Graphs** ([arXiv:2609.09153](https://arxiv.org/abs/2609.09153)): an explicit, attributed graph of tools, skills, and statuses; locate–extract–generate situational guidance; and offline evolution with rejection memory.

Includes an optional **FastMCP overlay** for Cursor, Claude Code, and other MCP clients.

*(Currently in pre-release testing — install directly from source)*.

---

### The Problem It Solves

Standard LLM agents rely on an ever-growing linear conversation history. Over long-horizon tasks, agents suffer from **planning drift, out-of-order tool calls, and repetitive action loops**.

Procedural Graphs replace flat context histories with an explicit, evolving state machine:
1. **At runtime (Inference):** The agent only receives *situational guidance* for its current step and immediate valid transitions, cutting prompt bloat.
2. **Playbook evolution (agent-in-the-loop):** Failed steps are recorded in session memory; the host agent proposes a recovery and applies it with `apply_graph_mutation`. No API keys.

---

### Quick Setup (From Source)

Requires **Python 3.11+**.

```bash
git clone https://github.com/<YOUR-USERNAME-OR-ORG>/procedural-graphs.git
cd procedural-graphs

# Create & activate a virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .\.venv\Scripts\Activate.ps1

# Install with MCP dependencies
pip install "mcp[cli]" -e .
```

---

### Python SDK Usage

```python
from procedural_graphs import (
    ProceduralGraph,
    ProcedureNode,
    TransitionEdge,
    GuidedAgent,
)

# 1. Build an attributed procedural graph
graph = ProceduralGraph()
graph.add_procedure(ProcedureNode(id="Start", name="Start", description="Entrypoint"))
graph.add_procedure(ProcedureNode(id="migrate", name="migrate", kind="tool"))
graph.add_transition(
    TransitionEdge(
        source="Start",
        target="migrate",
        condition="Schema change approved",
        guidance="Run the migration playbook.",
        pitfalls="Do not skip the backup.",
    )
)

# 2. Run agent with situational guidance
def agent_fn(query, history, guidance):
    print(f"Advisory Guidance: {guidance.text}")
    return {"action": "migrate", "output": "Migration complete"}

agent = GuidedAgent(agent_fn, graph, evolve=False)
result = agent.run("Deploy schema update")
```

---

### Editor Setup (Cursor & Claude Code)

Serve a YAML playbook via MCP to give your editor's AI assistant live procedural guidance (`get_procedural_guidance`, `advance_procedure`, `report_procedural_anomaly`, `apply_graph_mutation`).

#### Cursor
In your `.cursor/mcp.json` (or `cursor-settings.json`):
```json
{
  "mcpServers": {
    "procedural-graphs": {
      "command": "<PATH_TO_VENV>/bin/python",
      "args": [
        "-m", "procedural_graphs.cli",
        "serve",
        "--graph", "examples/feature-dev.yaml"
      ]
    }
  }
}
```
*(On Windows, use: `"C:\\path\\to\\.venv\\Scripts\\python.exe"`).*

#### Claude Code (Terminal)
```bash
claude mcp add procedural-graphs -- <PATH_TO_VENV>/bin/python -m procedural_graphs.cli serve --graph examples/feature-dev.yaml
```

---

### Ready-Made Playbooks

We provide turnkey SOPs in the `examples/` directory so you don't have to write YAML from scratch:

| Playbook | Purpose | File |
| :--- | :--- | :--- |
| **Feature Dev (TDD)** | Enforces test-first development before code generation | `examples/feature-dev.yaml` |
| **Safe DB Migration** | Enforces snapshots, dry-runs, and lock checks | `examples/safe-db-migration.yaml` |
| **Security Audit** | Enforces auth boundary verification and CVE checks | `examples/security-audit.yaml` |

---

### Testing

Run the test suite using `pytest`:

```bash
pip install pytest
pytest -v
```

The test suite in `tests/` verifies:
* **Graph Topology:** Cycle handling, attribute validation, and serialization (`test_graph.py`).
* **Inference Guidance:** Node localization from trajectories and prompt compilation (`test_guidance.py`).
* **Self-Evolution:** Offline LLM refiner loops, mutation validation, and rejection memory deduplication (`test_evolver.py`).
* **MCP session helpers:** Agent-in-the-loop mutation apply/persist and anomaly recording without a live server (`test_mcp_session.py`).

---

### Citation

```bibtex
@article{lu2026procedural,
  title={Procedural Graphs: Self-Evolving Execution Structures for LLM Agents},
  author={Lu, Yuxing and Chen, Yicheng and Wu, Shanchan and Ar{\i}k, Sercan {\"O}},
  journal={arXiv preprint arXiv:2609.09153},
  year={2026}
}
```

---

### License

[MIT](LICENSE)
