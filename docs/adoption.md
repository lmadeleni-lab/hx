# Adoption Walkthrough

Get from zero to governed AI coding in under 5 minutes.

## Prerequisites

- Python 3.11 or newer
- `git`
- A terminal (macOS, Linux, or WSL)

## 1. Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install .
```

## 2. Initialize Your Repo

```bash
cd your-project
hx setup
hx bootstrap
```

`hx setup` does everything in one command:
- Detects your primary language (Python, TypeScript, Go, etc.)
- Creates `HEXMAP.json` — maps your repo into hexagonal cells
- Creates `POLICY.toml` — governance rules, sandbox, command allowlist
- Creates `AGENTS.md` and `TOOLS.md` — agent behavior guidance
- Validates the topology and suggests a policy mode (dev/ci/release)

`hx bootstrap` generates agent-specific configs:
- `.claude/settings.json` — MCP server auto-discovery for Claude Code
- `.claude/CLAUDE.md` — project governance instructions
- `.claude/memory/` — persistent context files
- `GEMINI.md` — Gemini-specific instructions

## 3. Check Project Health

```bash
hx readiness
```

This runs 8 checks: scaffold files, hexmap quality, policy fitness,
git status, test coverage by cell, audit history, risk profile, and
agent config. Each check passes or fails with a specific recommendation.

```bash
hx suggest
```

Suggests low-risk starter tasks based on your repo's actual state —
missing tests, undocumented cells, lint issues, risky ports. Each
suggestion includes a ready-to-run `hx run` command.

## 4. Connect Your Agent

### Claude Code (automatic)
Just open the repo — Claude Code discovers `.claude/settings.json`.

### Codex CLI
```bash
hx codex setup
codex --login
codex
```

### Gemini CLI
```bash
hx gemini setup
gemini
```

### Any MCP client
```bash
hx mcp serve --transport stdio
```

## 5. Plan Your Work

For simple tasks, run directly:
```bash
hx run 'Fix the null check in src/auth.py line 42' --cell src
```

For complex work, plan first:
```bash
hx plan create 'Migrate to OAuth2' \
  --step 'Add client library' --step-cell src \
  --step 'Update login endpoint' --step-cell src \
  --step 'Add integration tests' --step-cell tests --step-after '0,1'
hx plan show
```

Need prompt ideas? Run `hx samples` for copy-paste examples.

## 6. Check the Reasoning Gate

Before running expensive LLM tasks:
```bash
hx gate --cell src --radius 1
```

This tells you whether the system can handle the task locally
(deterministic rules, no LLM cost) or needs LLM consultation.
Modes: `LOCAL`, `LLM_SCOPED`, `LLM_FULL`, `ESCALATE`.

## 7. Run a Governed Task

```bash
export ANTHROPIC_API_KEY='sk-ant-...'
hx run 'Add input validation to the login endpoint' --cell src
```

The agent loop will:
1. Evaluate the reasoning gate (skip LLM if local reasoning suffices)
2. Build a scoped or full system prompt with memory context
3. Stream Claude's response with tool calls
4. Execute tools through the governance layer
5. Check holonomy for feedback integrity after port-affecting calls
6. Record everything in the audit trail

## 8. The Governance Flow

When the agent makes changes, the flow is:

```
repo.stage_patch → port.check → proof.collect → proof.verify → repo.commit_patch
```

- **Breaking changes** trigger elevated proof tiers and human approval
- **High-risk ports** get flagged with risk scores
- **Commit is blocked** if proofs are unsatisfied or approval is missing
- Every denial message tells you **what went wrong and how to fix it**

## 9. Monitor and Audit

```bash
hx status           # governance dashboard
hx log              # audit summary + risky ports
hx percolation      # hex lattice phase health
hx memory summarize # refresh state for next session
hx resume           # load restart context
```

## 10. Interpret Results Correctly

| Category | Status | Meaning |
|----------|--------|---------|
| **Deterministic** | Exact | Cell resolution, authorization, proofs, audit |
| **Heuristic** | Policy-tunable | Risk scores, boundary pressure, proof tiers |
| **LLM output** | Best-effort | Code changes, summaries, reasoning |

Proof, risk, and benchmark outputs are governance-grade.
Metric weights are heuristic and documented as such.
The LLM generates code — the system enforces quality.

## What If Something Goes Wrong?

| Problem | Solution |
|---------|----------|
| "Path denied by policy sandbox" | Check `POLICY.toml` denylist — the error shows which rule matched |
| "Outside allowed radius" | Use `--radius 2` or `--cell <target>` — the error lists allowed cells |
| "Proof obligations not satisfied" | Run `proof.collect` then `proof.verify` — check test output |
| "Human approval required" | The agent will prompt you — type `y` to approve breaking changes |
| "Could not resolve active cell" | Use `--cell <id>` — run `hx hex show <id>` to find the right cell |
| "ANTHROPIC_API_KEY not set" | Get a key at console.anthropic.com, then `export ANTHROPIC_API_KEY=...` |
| Hexmap disconnected warning | Normal for auto-built maps — add neighbor links in `HEXMAP.json` |

See also: [metrics.md](metrics.md), [contracts.md](contracts.md),
[security.md](security.md), [benchmarking.md](benchmarking.md).
