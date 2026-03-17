from __future__ import annotations

import json


def starter_hexmap() -> str:
    data = {
        "version": "1",
        "cells": [
            {
                "cell_id": "root",
                "paths": ["src/**", "tests/**", "docs/**"],
                "summary": "Starter root cell. Split into smaller cells as the repo grows.",
                "invariants": ["Cross-cell changes require declared ports."],
                "tests": ["pytest -q"],
                "neighbors": [None, None, None, None, None, None],
                "ports": [None, None, None, None, None, None],
            }
        ],
        "port_types": {},
        "parent_groups": [],
    }
    return json.dumps(data, indent=2) + "\n"


def policy_toml() -> str:
    return """mode = "dev"
audit_log_path = ".hx/audit"
artifact_store_path = ".hx/artifacts"
default_radius_max_auto_approve = 1

[path_sandbox]
allowlist = [
  "src/**",
  "tests/**",
  "docs/**",
  "*.md",
  "HEXMAP.json",
  "POLICY.toml",
  ".github/workflows/**",
]
denylist = [".env", ".env.*", "secrets/**", "**/*.pem", "**/*.key"]

[commands]
allowed_prefixes = [
  "python",
  "python3",
  "pytest",
  "ruff",
  "git status",
  "git diff",
  "git apply",
]

[approval_gates]
breaking_changes = true
dependency_changes = true
touching_config_or_secrets = true
modifying_lockfiles = true

[limits]
default_timeout_s = 30
max_timeout_s = 120
max_output_bytes = 50000
max_concurrency = 2

[modes.dev]
require_human_for_breaking = true

[modes.ci]
require_human_for_breaking = true

[modes.release]
require_human_for_breaking = true
strict_risk_threshold = 0.65

[risk_weights]
entropy = 0.35
churn = 0.25
pressure = 0.25
failures = 0.15
"""


def agents_template() -> str:
    return """# AGENTS.md

This repository uses `hx` for locality-aware coding work.

## Rules

- Every task must declare `active_cell_id` and `context_radius`.
- Radius starts at `R0`. Expansions must be justified and logged.
- Cross-cell interactions must route through declared ports.
- Boundary-changing diffs require proof-carrying validation before commit.
- Prefer edits inside the active cell; treat radius expansion as an exception.
- If `hx` denies a change, treat the denial reason as the next required action:
  re-stage, collect proof, obtain approval, or justify a wider radius.
"""


def tools_template() -> str:
    return """# TOOLS.md

## Golden Path

1. Resolve the active cell.
2. Ask `hx` for allowed cells at the requested radius.
3. Load context with `hex.context` (defaults to summary mode — use
   `detail='full'` only when needed).
4. Read files with `repo.read` (supports `offset`/`limit` for large files).
5. Search with `repo.search` (pre-filtered to cell scope, max 20 results).
6. Stage patches before commit.
7. If approval is required, run `repo.approve_patch`.
8. Run `port.check`, `proof.collect`, `proof.verify`, then `repo.commit_patch`.

If commit is denied:

- re-stage if the patch changed after analysis
- complete missing proof obligations
- obtain approval for breaking or high-risk changes
- justify a radius expansion before reading or editing outside the allowed cells

## Core MCP Tools

- `hex.resolve_cell` — resolve file path to cell
- `hex.allowed_cells` — list cells at radius
- `hex.context` — load context (summary or full mode)
- `hex.parent_groups` — parent group overview
- `port.describe` — port contract details
- `port.check` — boundary impact analysis
- `repo.read` — read file (with offset/limit)
- `repo.search` — search within scope (with max_results)
- `repo.stage_patch` — stage a unified diff
- `repo.approve_patch` — approve breaking changes
- `proof.collect` — run proof checks
- `proof.verify` — verify proof artifacts
- `repo.commit_patch` — finalize commit
- `cmd.run` — run allowed shell command
- `tests.run` — run cell tests
- `metrics.compute` — compute task metrics
"""


def benchmark_template() -> str:
    return """# BENCHMARK.md

`hx benchmark run` consumes a JSON task battery.

Each task should include:

- `task_id`
- `difficulty`
- `description`
- `seed_branch`
- `repeats` (recommended for public comparisons; use `>= 2` for confidence margins)
- `baseline_commands`
- `treatment_commands`
- `acceptance_checks`
- `baseline_run_ids`
  optional audit runs with recorded metrics for baseline locality/proof coverage
- `treatment_run_ids`
  optional audit runs with recorded metrics for treatment locality/proof coverage

`hx benchmark run` treats benchmark output as descriptive by default. Confidence
margins are only reported when repeated paired runs are available. Locality and
proof-coverage summaries are only reported when matching audit run ids are
provided. The shipped example battery should be treated as a starter template,
not a research-grade benchmark suite.
"""
