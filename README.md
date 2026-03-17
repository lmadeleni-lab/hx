# hx

`hx` is an open-source local agentic coding harness built around a hexagonal
cell model with port-based governance, proof-carrying diffs, and safe-by-default
execution.

## Why

Most coding agents can edit broadly and quickly, but they do not natively enforce
bounded locality, interface governance, or replayable audit trails. `hx` acts as
the harness between an agent CLI and a repository. It enforces:

- active cell + radius scoped work (hexagonal topology)
- port contract checks for cross-cell interaction with orientation validation
- staged patch → analyze → proof → commit workflow
- auditable actions and best-effort replay
- architectural health metrics (boundary pressure, port churn, entropy, holonomy)
- token-optimized agent context with progressive loading

## Status

Current version: **0.8.0**

The framework includes:

- **One-command onboarding**: `hx setup` auto-detects language, scaffolds
  templates, builds hexmap, validates topology, and suggests a policy mode
- **Agent config scaffolding**: `hx bootstrap` generates `.claude/CLAUDE.md`
  and memory files derived from live HEXMAP and POLICY
- **Project health checks**: `hx readiness` runs 8-point diagnostics with
  actionable recommendations
- **Task suggestions**: `hx suggest` analyzes the repo and recommends low-risk
  starter tasks with ready-to-run commands
- **Governed agent loop**: `hx run '<task>'` orchestrates Claude with full
  governance, streaming output, and memory-injected system prompts
- **Token optimization**: chunked file reads, pre-filtered search, progressive
  context loading, surface caching, and tool result compression
- **Hex lattice mathematics**: percolation threshold tracking, information-weighted
  boundary pressure with isoperimetric normalization, holonomy/cocycle
  cycle-consistency checks, and nonlinear risk scoring with interaction terms
- **MCP server**: stdio transport with 40+ governance tools for Codex, Gemini,
  and Claude Code integration
- **Benchmark framework**: paired-run reporting with variance summaries

## Install

Prerequisites:

- Python 3.11 or newer
- `git`

From a source checkout:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install .
hx --help
```

For contributors:

```bash
pip install -e .[dev]
```

## Quickstart

The fastest path from zero to productive:

```bash
hx setup              # scaffolds everything, builds hexmap
hx bootstrap          # generates agent config (.claude/)
hx readiness          # confirms project health
hx suggest            # shows what to work on first
hx run '<task>'       # run a governed agent task
```

### Manual initialization (alternative)

```bash
hx init
hx hex build
hx hex validate
```

### Codex integration

```bash
hx codex setup
codex --login
codex
```

`hx codex setup` writes the MCP entry into `~/.codex/config.toml`. Codex
spawns `hx` automatically through MCP — do not run `hx mcp serve` manually.

## Commands

| Command | Description |
|---------|-------------|
| `hx setup` | One-command guided onboarding |
| `hx bootstrap` | Scaffold agent config files (.claude/) |
| `hx readiness` | Project health check with recommendations |
| `hx suggest` | Suggest low-risk starter tasks |
| `hx run '<task>'` | Run a governed agent task |
| `hx status` | Governance status dashboard |
| `hx init` | Initialize hx workspace (templates only) |
| `hx hex build` | Build HEXMAP from repo structure |
| `hx hex validate` | Validate HEXMAP topology |
| `hx hex show <cell>` | Render cell neighborhood |
| `hx hex watch <cell>` | Live cell monitoring TUI |
| `hx hex parent show <id>` | Parent group view |
| `hx log` | Audit summary with risky ports |
| `hx memory summarize` | Refresh state summaries |
| `hx resume` | Load compacted restart context |
| `hx mcp serve` | Start MCP stdio server |
| `hx doctor` | Environment prerequisite check |
| `hx benchmark run` | Run benchmark battery |
| `hx replay <run_id>` | Replay an audit run |

## Key Concepts

- **Cells**: hexagonal regions of the codebase (6 neighbors each)
- **Ports**: directed edges between cells with contracts, orientation, and proof requirements
- **Radius**: BFS scope control — R0 = active cell only, R1 = +neighbors
- **Proof tiers**: standard → elevated → strict based on change risk
- **Parent groups**: coarse topology layer for multi-scale governance
- **Percolation threshold**: port occupation tracked against p_c=1/2
- **Holonomy**: cycle-consistency checks detect global contract violations

## Documentation

- [docs/adoption.md](docs/adoption.md) — golden path walkthrough
- [docs/hex.md](docs/hex.md) — hex model specification
- [docs/contracts.md](docs/contracts.md) — port contracts and proof tiers
- [docs/metrics.md](docs/metrics.md) — metric definitions and maturity
- [docs/memory.md](docs/memory.md) — context compaction
- [docs/security.md](docs/security.md) — security posture
- [docs/benchmarking.md](docs/benchmarking.md) — evaluation methodology
- [docs/codex.md](docs/codex.md) — Codex integration
- [docs/gemini.md](docs/gemini.md) — Gemini integration
- [docs/release.md](docs/release.md) — release policy
- [docs/roadmap.md](docs/roadmap.md) — future direction
- [CHANGELOG.md](CHANGELOG.md) — version history
- [plan.md](plan.md) — execution plan
