# hx

[![CI](https://github.com/lmadeleni-lab/hx/actions/workflows/ci.yml/badge.svg)](https://github.com/lmadeleni-lab/hx/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.11.0-orange)](CHANGELOG.md)

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

| Property | Guarantee | Benefit |
|----------|-----------|---------|
| **Optimal isoperimetric ratio** | Smallest boundary per area | Minimizes state leakage |
| **Exact BFS bounds** | 3R²+3R+1 cells at radius R | Know token budget before LLM call |
| **Percolation p_c=1/2** | Exact phase transition | Local vs global reasoning boundary |
| **Holonomy on triangles** | Cocycle consistency | Detect feedback loop drift |
| **Renormalization groups** | Multi-scale coarsening | Parent-level reasoning |

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
hx bootstrap          # generate agent config (.claude/, GEMINI.md)
hx readiness          # 8-point health check
hx suggest            # discover starter tasks
hx samples            # see example prompts
hx run '<task>'       # governed agent loop
```

## Commands

### Onboarding & Planning
| Command | Description |
|---------|-------------|
| `hx setup` | Auto-detect language, scaffold, build hexmap, validate |
| `hx bootstrap` | Generate `.claude/settings.json`, `CLAUDE.md`, `GEMINI.md`, memory files |
| `hx readiness` | 8-point project health check with recommendations |
| `hx suggest` | Suggest low-risk starter tasks with ready-to-run commands |
| `hx samples` | Show example task prompts for `hx run` |
| `hx plan create '<goal>'` | Create multi-step task plan with dependencies |
| `hx plan show` | View current plan progress |
| `hx plan advance <step>` | Mark a step as completed |

### Reasoning Engine
| Command | Description |
|---------|-------------|
| `hx run '<task>'` | Governed agent loop with reasoning gate |
| `hx gate --cell <id>` | Evaluate reasoning mode (local/scoped/full/escalate) |
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
| `hx hex parent watch <id>` | Live parent monitoring |

### Governance & Audit
| Command | Description |
|---------|-------------|
| `hx log` | Audit summary with risky ports |
| `hx memory summarize` | Refresh state summaries |
| `hx resume` | Load compacted restart context |
| `hx replay <run_id>` | Replay an audit run |
| `hx doctor` | Environment prerequisite check |
| `hx benchmark run <battery>` | Run evaluation battery |

### Integration
| Command | Description |
|---------|-------------|
| `hx mcp serve` | Start MCP stdio server (40+ tools) |
| `hx codex setup` | Configure Codex CLI MCP integration |
| `hx codex status` | Check Codex integration state |
| `hx gemini setup` | Configure Gemini CLI MCP integration |
| `hx gemini status` | Check Gemini integration state |

## Agent Integration

| Agent | Setup | Config Generated | Auto-Discovery |
|-------|-------|-----------------|----------------|
| **Claude Code** | `hx bootstrap` | `.claude/settings.json` + `CLAUDE.md` | MCP auto-discovered |
| **Codex CLI** | `hx codex setup` | `~/.codex/config.toml` | MCP entry injected |
| **Gemini CLI** | `hx gemini setup` | `~/.gemini/settings.json` | MCP entry injected |
| **Any MCP** | `hx mcp serve --transport stdio` | — | Manual connection |

### Zero-to-agent flow

```bash
hx setup && hx bootstrap     # scaffolds everything + agent configs
hx gemini setup               # if using Gemini
hx codex setup                # if using Codex
# Claude Code: just open the repo — auto-discovers .claude/settings.json
```

## Key Concepts

### Stateful Reasoning
- **Reasoning gate**: evaluates occupation, pressure, risk → decides
  LOCAL / LLM_SCOPED / LLM_FULL / ESCALATE
- **State transitions**: incremental updates with drift detection
- **Feedback integrity**: holonomy check after each execution cycle
- **Transport-cost prompts**: LLM sees only high-uncertainty boundaries
- **Task planning**: multi-step work with cell targeting and dependencies

### Hex Governance
- **Cells**: hexagonal code regions (6 neighbors, bounded degree)
- **Ports**: directed edges with contracts, orientation, proof requirements
- **Radius**: BFS scope — R0 = active cell, R1 = +neighbors
- **Proof tiers**: standard / elevated / strict based on risk
- **Parent groups**: coarse topology for multi-scale reasoning

### Mathematics
- **Percolation**: port occupation tracked against p_c=1/2
- **Isoperimetric normalization**: boundary pressure relative to hex optimum
- **Holonomy**: cocycle consistency around triangular cycles
- **Information-weighted edges**: pairwise transport cost with asymmetry
- **Nonlinear risk**: entropy x churn interaction term
- **Graph invariants**: V, E, components, Euler characteristic

### Token Optimization
- Chunked file reads with auto-truncation at 100KB
- Pre-filtered search scoped to cell paths (max 20 results)
- Progressive context (summary default, full on demand)
- Surface caching in `.hx/state/surfaces.json`
- Tool result compression (null stripping, dedup, truncation)

## MCP Tools (40+)

| Category | Tools |
|----------|-------|
| **Hex topology** | `hex.resolve_cell`, `hex.allowed_cells`, `hex.context`, `hex.neighbors`, `hex.parent_*` |
| **Ports** | `port.describe`, `port.surface`, `port.surface_diff`, `port.check` |
| **Repository** | `repo.read`, `repo.search`, `repo.stage_patch`, `repo.commit_patch`, `repo.approve_patch`, `repo.abort_patch`, `repo.diff`, `repo.files_touched` |
| **Proofs** | `proof.collect`, `proof.verify`, `proof.attach` |
| **Execution** | `cmd.run`, `tests.run` |
| **Metrics** | `metrics.compute`, `metrics.report`, `metrics.parent_report`, `risk.top_ports` |

## Documentation

| Doc | Contents |
|-----|----------|
| [adoption.md](docs/adoption.md) | Golden path walkthrough |
| [hex.md](docs/hex.md) | Hex model specification |
| [contracts.md](docs/contracts.md) | Port contracts and proof tiers |
| [metrics.md](docs/metrics.md) | Metric definitions and maturity |
| [memory.md](docs/memory.md) | Context compaction system |
| [security.md](docs/security.md) | Security posture and threat model |
| [benchmarking.md](docs/benchmarking.md) | Evaluation methodology |
| [codex.md](docs/codex.md) | Codex CLI integration |
| [gemini.md](docs/gemini.md) | Gemini CLI integration |
| [release.md](docs/release.md) | Release policy and versioning |
| [roadmap.md](docs/roadmap.md) | Future direction |
| [CHANGELOG.md](CHANGELOG.md) | Version history (v0.1.0 — v0.11.0) |

## License

[MIT](LICENSE)
