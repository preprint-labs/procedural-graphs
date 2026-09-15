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
git clone https://github.com/preprint-labs/procedural-graphs.git
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

Serve the **central playbook hub** via MCP. Playbooks live in `~/.procedural-graphs/playbooks/` (not in each git repo). On first run, bundled templates are copied there **only if a file of that name is missing** — user edits and `apply_graph_mutation` results are never overwritten. Session cursors are stored under `~/.procedural-graphs/sessions/`, keyed by repository, `task_id`, and playbook.

Do not copy YAML into project trees. Cursor `mcp.json` does not need `--graph`.

#### Cursor
In your `.cursor/mcp.json` (or `cursor-settings.json`):
```json
{
  "mcpServers": {
    "procedural-graphs": {
      "command": "<PATH_TO_VENV>/bin/python",
      "args": ["-m", "procedural_graphs.cli", "serve"]
    }
  }
}
```
*(On Windows, use: `"C:\\path\\to\\.venv\\Scripts\\python.exe"`).*

Optional: `--graph path/to/playbook.yaml` overrides the default playbook file for power users and tests. Named playbooks (e.g. `bugfix`) still resolve from the hub.

#### Claude Code (Terminal)
```bash
claude mcp add procedural-graphs -- <PATH_TO_VENV>/bin/python -m procedural_graphs.cli serve
```

Call `list_available_playbooks` to see hub stems, then `get_procedural_guidance(playbook="feature-dev", task_id="...")`. Mutations written by `apply_graph_mutation` update the central file, so learning in one repository is visible in another.

---

### Ready-Made Playbooks

Bundled templates ship inside the Python package (`procedural_graphs/default_playbooks/`) and seed the user hub. `examples/` in this repo is a browseable copy of the same schemas — it is not a per-project install path.

| Playbook | Purpose | Stem |
| :--- | :--- | :--- |
| **Feature Dev (TDD)** | Spec → failing tests → implement → verify | `feature-dev` |
| **Bugfix** | Repro → diagnose → patch → test | `bugfix` |
| **Safe DB Migration** | Snapshot → dry-run → migrate | `safe-db-migration` |
| **Security Audit** | CVE scan, auth boundaries, secret check | `security-audit` |
| **Service Deploy** | Inventory, additive migration, canary, soak, rollback | `deploy-playbook` |

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
* **Central hub:** Copy-missing-only seed, playbook path fallback, task-scoped sessions, hub mutations, and `serve` without `--graph` (`test_storage.py`, `test_hub_sessions.py`, `test_cli.py`).

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
