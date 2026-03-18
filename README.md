# hx

[![CI](https://github.com/lmadeleni-lab/hx/actions/workflows/ci.yml/badge.svg)](https://github.com/lmadeleni-lab/hx/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.11.0-orange)](CHANGELOG.md)

**Stop letting AI agents write code without guardrails.**

`hx` is a stateful reasoning engine that makes AI coding agents safe,
auditable, and architecturally aware. It wraps your repo in a hexagonal
cell graph where every change is scoped, every boundary is governed,
and every action is tracked.

The LLM is a **consultant**. `hx` is the **system** — it owns the state,
runs the simulation, scores the risk, and decides when to call the LLM
versus when deterministic rules are enough.

## The Problem

AI coding agents are powerful but dangerous:

- They edit files **anywhere** with no scope control
- They make changes that **break interfaces** between modules
- They have **no memory** of what they did or why
- They **burn tokens** reading entire files when they need 10 lines
- There is **no audit trail** when something goes wrong
- You cannot **plan multi-step work** — each task is isolated

## How hx Solves This

```
state -> reasoning gate -> simulation -> decision -> execution -> feedback -> state
         (local/LLM?)     (deterministic)  (scored)   (governed)   (audited)
```

| Problem | hx Solution |
|---------|-------------|
| Agents edit anywhere | **Cell + radius** scoping — agents can only touch files in their assigned hexagonal cell |
| Breaking interfaces | **Port contracts** — cross-cell changes are detected, classified, and require proof |
| No memory | **Stateful engine** — audit trail, state transitions, memory injection into prompts |
| Wasted tokens | **Progressive loading** — summary first, detail on demand; chunked reads; compressed results |
| No audit trail | **Append-only audit log** with file locking, replayable runs, governance artifacts |
| No planning | **Task planner** — multi-step plans with cell targeting and dependency tracking |
| LLM always called | **Reasoning gate** — decides LOCAL (free) vs LLM_SCOPED (cheap) vs LLM_FULL (expensive) |

## Benefits

**For teams using AI coding agents:**
- Every AI change is scoped to a cell and radius — no surprise edits across the codebase
- Breaking changes require human approval — the AI cannot bypass this
- Full audit trail — know exactly what happened, when, and why
- Risk scoring catches problems before they reach production

**For architects:**
- Hexagonal topology maps naturally to module boundaries
- Multi-scale reasoning via parent groups — zoom out without losing detail
- Boundary pressure metrics tell you where your architecture is stressed
- Holonomy checks catch global inconsistencies that local reviews miss

**For cost-conscious teams:**
- Reasoning gate skips the LLM when deterministic rules suffice
- Token optimization reduces context by 40-50% when the LLM is needed
- Surface caching avoids re-parsing files on every tool call
- Progressive context loading: summary mode uses ~100 tokens vs ~800 for full

**For security teams:**
- Path traversal protection on every file read
- Shell injection blocking with argument pattern validation
- LLM cannot self-approve, cannot override proof obligations
- Deny-by-default policy sandbox

## Quickstart

```bash
# 1. Install (30 seconds)
python3 -m venv .venv && source .venv/bin/activate
pip install .

# 2. Initialize your repo (30 seconds)
cd your-project
hx setup            # auto-detects language, builds hexmap, scaffolds policy
hx bootstrap        # generates agent configs (.claude/, GEMINI.md)

# 3. Check what's ready (10 seconds)
hx readiness        # 8-point health check
hx suggest          # repo-specific task recommendations

# 4. See example prompts
hx samples          # copy-paste examples for common tasks

# 5. Plan multi-step work (optional)
hx plan create 'Add user authentication' \
  --step 'Add auth middleware' --step-cell src \
  --step 'Add login endpoint' --step-cell src \
  --step 'Add auth tests' --step-cell tests --step-after '0,1'
hx plan show        # view progress

# 6. Check reasoning mode
hx gate --cell src  # LOCAL? LLM_SCOPED? LLM_FULL? ESCALATE?

# 7. Run a governed task
export ANTHROPIC_API_KEY='sk-ant-...'
hx run 'Add input validation to the login endpoint. \
  Check for empty email, SQL injection, and add tests.' --cell src

# 8. Monitor
hx status           # governance dashboard
hx log              # audit trail with risky ports
hx percolation      # hex lattice phase monitor
```

**Everything except step 7 works without an API key.**

## Why Hexagons (Not Just Any Graph)

The degree-6 hex lattice provides mathematical guarantees that matter:

| Property | What It Means In Practice |
|----------|--------------------------|
| **Degree-6 bound** | At radius R, scope is exactly 3R^2+3R+1 cells. You know your token budget before calling the LLM. R1=7 cells, R2=19 cells. |
| **Best isoperimetric ratio** | Among all regular tilings, hexagons have the smallest boundary for a given area. Your governance boundaries leak the least. |
| **Percolation at p_c=1/2** | When more than half your ports are active, changes can propagate unboundedly. `hx percolation` warns you before this happens. |
| **Holonomy on triangles** | Cycle-consistency checks detect when a sequence of individually-valid changes creates a globally-invalid state. |
| **Renormalization** | Parent groups (7 cells each) create a coarser view. Reason at the parent level, drill down only when needed. |

## What's Deterministic vs Heuristic vs LLM

| Category | What | Requires LLM? |
|----------|------|---------------|
| **Deterministic** | Cell resolution, authorization, path sandbox, patch staging, SHA256 integrity, surface extraction (Python/TS/Go), port impact classification, audit trail, graph invariants, holonomy checks, state transitions | No |
| **Heuristic** | Risk scoring (normalized [0,1] with interaction terms), architecture potential, boundary pressure (isoperimetrically normalized), proof tier escalation, reasoning gate thresholds, parent cohesion | No |
| **LLM-assisted** | `hx run` agent loop, system prompt construction, tool call orchestration, streaming output | Yes (Anthropic API) |

**The governance system, simulation, and decision logic are fully deterministic.
The LLM is only used for generating code changes — never for enforcement.**

## Commands

### Getting Started
| Command | What It Does |
|---------|-------------|
| `hx setup` | One-command init: detect language, scaffold, build hexmap |
| `hx bootstrap` | Generate `.claude/settings.json`, `CLAUDE.md`, `GEMINI.md` |
| `hx readiness` | 8-point health check with recommendations |
| `hx suggest` | Repo-specific task suggestions with run commands |
| `hx samples` | Example prompts for common tasks |

### Planning & Reasoning
| Command | What It Does |
|---------|-------------|
| `hx plan create '<goal>'` | Multi-step plan with cell targeting + dependencies |
| `hx plan show` | View plan progress |
| `hx plan advance <n>` | Mark step n as done, find next |
| `hx gate --cell <id>` | Reasoning mode: LOCAL / LLM_SCOPED / LLM_FULL / ESCALATE |
| `hx run '<task>'` | Governed agent loop with reasoning gate |
| `hx percolation` | Real-time percolation phase monitor |
| `hx status` | Governance dashboard |

### Topology & Governance
| Command | What It Does |
|---------|-------------|
| `hx hex build` | Build HEXMAP from repo structure |
| `hx hex validate` | Validate topology + holonomy + orientation |
| `hx hex show <cell>` | Render cell neighborhood |
| `hx hex watch <cell>` | Live monitoring TUI |
| `hx log` | Audit summary + risky ports |
| `hx memory summarize` | Refresh state summaries |
| `hx resume` | Load restart context |

### Integration
| Command | What It Does |
|---------|-------------|
| `hx mcp serve` | MCP stdio server (40+ tools) |
| `hx codex setup` | Configure Codex CLI |
| `hx gemini setup` | Configure Gemini CLI |
| `hx doctor` | Environment check |
| `hx benchmark run` | Run evaluation battery |

## Agent Integration

| Agent | Setup | What Gets Generated |
|-------|-------|-------------------|
| **Claude Code** | `hx bootstrap` | `.claude/settings.json` + `CLAUDE.md` + memory |
| **Codex** | `hx codex setup` | `~/.codex/config.toml` MCP entry |
| **Gemini** | `hx gemini setup` | `~/.gemini/settings.json` MCP entry |
| **Any MCP** | `hx mcp serve --transport stdio` | Direct connection |

```bash
# Zero-to-agent in 3 commands:
hx setup && hx bootstrap && hx codex setup  # or hx gemini setup
```

## MCP Tools (40+)

| Category | Tools |
|----------|-------|
| **Hex** | `resolve_cell`, `allowed_cells`, `context`, `neighbors`, `parent_*` |
| **Ports** | `describe`, `surface`, `surface_diff`, `check` |
| **Repo** | `read`, `search`, `stage_patch`, `commit_patch`, `approve_patch`, `abort_patch`, `diff`, `files_touched` |
| **Proofs** | `collect`, `verify`, `attach` |
| **Exec** | `cmd.run`, `tests.run` |
| **Metrics** | `compute`, `report`, `parent_report`, `risk.top_ports` |

## Security

- Path traversal protection on all file reads (resolve + is_relative_to check)
- Shell injection regex + dangerous argument blocking (`sh -c`, `bash -c`, `--exec`)
- Proof obligations set by `port.check` — **LLM cannot override**
- Approval requires `human:` prefix — **LLM cannot self-approve**
- Deny-by-default policy sandbox (allowlist + denylist)
- Audit trail with advisory file locking
- Port direction enforced as enum (export/import/bidirectional/none)

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
| [codex.md](docs/codex.md) | Codex integration |
| [gemini.md](docs/gemini.md) | Gemini integration |
| [release.md](docs/release.md) | Release policy |
| [roadmap.md](docs/roadmap.md) | Future direction |
| [CHANGELOG.md](CHANGELOG.md) | Version history (v0.1.0 — v0.11.0) |

## License

[MIT](LICENSE)
