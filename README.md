# hx

[![CI](https://github.com/lmadeleni-lab/hx/actions/workflows/ci.yml/badge.svg)](https://github.com/lmadeleni-lab/hx/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.11.0-orange)](CHANGELOG.md)

A **stateful reasoning engine** for agentic code development. The LLM is
a consultant — `hx` owns state, simulation, and decisions.

```
state -> reasoning gate -> simulation -> decision -> execution -> feedback -> state
         (local/LLM?)     (deterministic)  (scored)   (governed)   (audited)
```

## Quickstart (2 minutes)

```bash
# Install
python3 -m venv .venv && source .venv/bin/activate
pip install .

# Initialize your repo
cd your-project
hx setup                    # detects language, builds hexmap, scaffolds everything
hx bootstrap                # generates .claude/ config + GEMINI.md

# Explore
hx readiness                # health check — see what's ready, what needs work
hx suggest                  # get task recommendations
hx samples                  # see example prompts

# Plan multi-step work
hx plan create 'Add OAuth2' \
  --step 'Add client library' --step-cell src \
  --step 'Update endpoints'   --step-cell src \
  --step 'Add integration tests' --step-cell tests --step-after '0,1'
hx plan show

# Check reasoning mode before running
hx gate --cell src          # LOCAL? LLM_SCOPED? LLM_FULL?

# Run a governed task
export ANTHROPIC_API_KEY='sk-ant-...'
hx run 'Add input validation to the login endpoint' --cell src

# Monitor
hx status                   # governance dashboard
hx percolation              # percolation phase monitor
hx log                      # audit trail
```

## Why Hexagons

| Property | Mathematical Guarantee | What It Means |
|----------|----------------------|---------------|
| **Degree-6 bound** | Scope = 3R^2+3R+1 cells | Know token budget before LLM call |
| **Isoperimetric optimum** | Smallest boundary/area ratio | Minimal state leakage across cells |
| **Percolation p_c=1/2** | Exact phase transition | Sharp local-vs-global reasoning boundary |
| **Holonomy** | Cocycle consistency on triangles | Detect feedback loop inconsistencies |
| **Renormalization** | Multi-scale coarsening | Parent-level reasoning without cell detail |

## What's Deterministic vs Heuristic vs Provider-Specific

### Fully Deterministic (no LLM, no tuning)
- Cell resolution, BFS radius expansion, authorization checks
- Path sandbox enforcement, command allowlist validation
- Patch staging, SHA256 integrity, file-touched tracking
- Surface extraction (Python/TypeScript/Go AST/regex)
- Port impact classification (breaking/compatible)
- Audit trail (append-only, locked writes)
- Graph invariants (V, E, components, Euler characteristic)
- Occupation fraction, isoperimetric bound
- Holonomy/cocycle checks, dual port validation
- State transitions (incremental, with drift detection)

### Heuristic (deterministic formula, policy-tunable weights)
- `policy_risk_score` — normalized [0,1], entropy/churn/pressure/failures + interaction
- `architecture_potential` — weighted sum with entropy x churn cross-term
- `boundary_pressure` — information-weighted graph cut, isoperimetrically normalized
- Proof tiers (standard/elevated/strict) — based on breaking + risk threshold
- Reasoning gate thresholds — PRESSURE_LOCAL_MAX, RISK_ESCALATE_MIN
- Parent cohesion, connectivity strength

### Provider-Specific (requires LLM API)
- `hx run` agent loop — calls Anthropic Claude API
- System prompt construction (scoped or full)
- Tool call orchestration and streaming
- Approval prompt (interactive terminal)

**Everything except the agent loop works without any API key.**

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
| **Claude Code** | `hx bootstrap` | `.claude/settings.json` + `CLAUDE.md` + memory files |
| **Codex** | `hx codex setup` | `~/.codex/config.toml` MCP entry |
| **Gemini** | `hx gemini setup` | `~/.gemini/settings.json` MCP entry |
| **Any MCP** | `hx mcp serve --transport stdio` | Direct connection |

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

- Path traversal protection on all file reads (resolve + prefix check)
- Shell injection regex + dangerous argument pattern blocking (`-c`, `--exec`, `-e`)
- Proof obligations enforced by `port.check`, not overridable by LLM
- Approval requires `human:` prefix — LLM cannot self-approve
- Deny-by-default policy sandbox (allowlist + denylist)
- Audit trail with file locking (fcntl.flock)
- Port direction validation (enum: export/import/bidirectional/none)

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
