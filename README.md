# hx

`hx` is an open-source **stateful reasoning engine** for agentic code
development, built on a hexagonal cell graph with port-based governance,
proof-carrying diffs, and mathematically-grounded decision logic.

The LLM is a **consultant**, not the system. `hx` owns the state, the graph,
the simulation, and the decision logic — calling the LLM only when
deterministic reasoning is insufficient.

## Architecture

```
state -> reasoning gate -> simulation -> decision -> execution -> feedback -> updated state
         (local/LLM?)     (deterministic)  (scored)   (governed)   (audited)
```

## Why Hexagons

The degree-6 hex lattice is not decorative — it provides mathematical
guarantees no other topology offers:

- **Optimal isoperimetric ratio**: smallest boundary per enclosed area among
  regular tilings — minimizes state leakage across partitions
- **Exact BFS bounds**: scope at radius R contains 3R²+3R+1 cells — know
  your token budget before calling the LLM
- **Percolation threshold p_c=1/2**: exact phase transition between "local
  reasoning suffices" and "global consultation needed"
- **Holonomy on triangles**: detect accumulated inconsistencies in the
  feedback loop via cycle-consistency checks
- **Renormalization groups**: parent hierarchy enables multi-scale reasoning

## Install

Prerequisites: Python 3.11+, git.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install .
hx --help
```

For contributors: `pip install -e .[dev]`

## Quickstart

```bash
hx setup              # one-command onboarding
hx bootstrap          # generate agent config (.claude/)
hx readiness          # 8-point health check
hx suggest            # discover starter tasks
hx gate --cell src    # check reasoning mode (local/scoped/full)
hx run '<task>'       # governed agent loop with reasoning gate
```

## Commands

### Onboarding
| Command | Description |
|---------|-------------|
| `hx setup` | Auto-detect language, scaffold, build hexmap, validate |
| `hx bootstrap` | Generate `.claude/CLAUDE.md` and memory files |
| `hx readiness` | Project health check with recommendations |
| `hx suggest` | Suggest low-risk starter tasks |

### Reasoning Engine
| Command | Description |
|---------|-------------|
| `hx run '<task>'` | Governed agent loop with reasoning gate |
| `hx gate` | Evaluate reasoning mode (local/scoped/full/escalate) |
| `hx percolation` | Real-time percolation phase monitor |
| `hx status` | Governance dashboard |

### Hex Topology
| Command | Description |
|---------|-------------|
| `hx hex build` | Build HEXMAP from repo structure |
| `hx hex validate` | Validate topology + holonomy + orientation |
| `hx hex show <cell>` | Render cell neighborhood |
| `hx hex watch <cell>` | Live monitoring TUI |
| `hx hex parent show <id>` | Parent group view |

### Governance
| Command | Description |
|---------|-------------|
| `hx log` | Audit summary with risky ports |
| `hx memory summarize` | Refresh state summaries |
| `hx resume` | Load restart context |
| `hx replay <run_id>` | Replay an audit run |
| `hx mcp serve` | Start MCP stdio server (40+ tools) |
| `hx doctor` | Environment check |
| `hx benchmark run` | Run evaluation battery |

## Key Concepts

### Stateful Reasoning
- **Reasoning gate**: evaluates occupation fraction, boundary pressure, and
  port risk to decide LOCAL (deterministic), LLM_SCOPED (focused prompt on
  hot edges), LLM_FULL, or ESCALATE (human needed)
- **State transitions**: incremental updates with before/after risk snapshots
  and drift detection — no full recomputation
- **Feedback integrity**: holonomy check on affected subgraph after each
  execution cycle detects accumulated inconsistencies
- **Transport-cost prompts**: when LLM is needed, only high-uncertainty
  boundaries are included — the LLM sees where it matters most

### Hex Governance
- **Cells**: hexagonal regions of the codebase (6 neighbors each)
- **Ports**: directed edges with contracts, orientation (export/import), and
  proof requirements
- **Radius**: BFS scope — R0 = active cell, R1 = +neighbors
- **Proof tiers**: standard / elevated / strict based on risk
- **Parent groups**: coarse topology for multi-scale reasoning

### Mathematics
- **Percolation**: port occupation tracked against p_c=1/2
- **Isoperimetric normalization**: boundary pressure relative to hex optimum
- **Holonomy**: cocycle consistency around triangular cycles
- **Information-weighted edges**: pairwise transport cost with asymmetry
- **Nonlinear risk**: entropy×churn interaction term in scoring
- **Graph invariants**: V, E, components, Euler characteristic tracked

### Token Optimization
- Chunked file reads with auto-truncation
- Pre-filtered search scoped to cell paths
- Progressive context (summary default, full on demand)
- Surface caching in `.hx/state/`
- Tool result compression

## Integration

- **Claude Code**: `hx bootstrap` generates `.claude/CLAUDE.md`
- **Codex**: `hx codex setup` configures MCP
- **Gemini**: `hx mcp serve --transport stdio`
- **Any MCP client**: 40+ governance tools

## Documentation

- [docs/adoption.md](docs/adoption.md) — golden path
- [docs/hex.md](docs/hex.md) — hex model
- [docs/contracts.md](docs/contracts.md) — port contracts
- [docs/metrics.md](docs/metrics.md) — metric definitions
- [docs/memory.md](docs/memory.md) — context compaction
- [docs/security.md](docs/security.md) — security posture
- [docs/benchmarking.md](docs/benchmarking.md) — evaluation
- [docs/codex.md](docs/codex.md) — Codex integration
- [docs/gemini.md](docs/gemini.md) — Gemini integration
- [docs/release.md](docs/release.md) — release policy
- [docs/roadmap.md](docs/roadmap.md) — future direction
- [CHANGELOG.md](CHANGELOG.md) — version history
