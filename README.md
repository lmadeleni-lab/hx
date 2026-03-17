# hx

`hx` is an open-source local agentic coding harness built around a hexagonal
cell model, governed cross-cell ports, proof-carrying diffs, and safe-by-default
execution.

## Why

Most coding agents can edit broadly and quickly, but they do not natively enforce
bounded locality, interface governance, or replayable audit trails. `hx` acts as
the harness between an agent CLI and a repository. It enforces:

- active cell + radius scoped work
- port contract checks for cross-cell interaction
- staged patch -> analyze -> proof -> commit workflow
- auditable actions and best-effort replay
- architectural health metrics such as boundary pressure, port churn, and port entropy

## Status

The current MVP includes:

- hex-aware CLI commands for init, validation, logging, replay, and benchmarking
- a second topology layer with derived parent hex groups for multiscale context
  compression and operator visibility
- an MCP stdio server with real end-to-end client validation
- staged proof-carrying patch workflows with approval gates
- audit-backed benchmark reporting with paired-run and variance summaries
- clean-install smoke coverage in CI for package build, install, and CLI startup

Current quantitative outputs are governance-oriented and reproducible, but still
heuristic unless explicitly documented otherwise. Today, `port_entropy` is
normalized; the remaining reported metrics are still heuristic or
policy-chosen.

## Install

The current supported host target is macOS terminal sessions. The install path
currently proven in CI is a clean install from a built package artifact or
source checkout, not a published PyPI release.

Standard prerequisites on macOS:

- `python3` 3.11 or newer
- `git`
- a terminal session on macOS
- Xcode Command Line Tools if `git` is not already installed:
  `xcode-select --install`

From a source checkout:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install .
hx --help
```

For contributors working on `hx` itself:

```bash
pip install -e .[dev]
```

## Quickstart

Initialize a new repository:

```bash
mkdir -p /tmp/hx-demo
cd /tmp/hx-demo
git init
hx init
hx hex build
hx hex validate
hx mcp serve --transport stdio
```

If you are connecting through Codex CLI, the native flow is:

```bash
hx codex setup
codex --login
codex
```

`hx codex setup` writes the MCP entry for the current repo into
`~/.codex/config.toml`. After that, Codex should spawn `hx` automatically. You
should not keep `hx mcp serve --transport stdio` running manually in a second
terminal when using Codex.

Running `hx` with no subcommand in a macOS terminal now shows the startup
screen and quick commands, similar to an interactive CLI landing view. During
command execution, `hx` now keeps a branded terminal shell visible with a
persistent `hx` header, colored phase-aware status updates, and a live
thinking/loading indicator on `stderr` so users can see what is happening
without breaking machine-readable output on `stdout`.

Optional interactive controls:

- `hx --ui-mode expanded ...` shows richer task-by-task streaming in the terminal
- `hx --ui-mode quiet ...` suppresses the interactive layer
- `hx hex show <cell_id> --radius 1` renders the active cell, six neighbor
  slots, and per-side fulfillment state
- `hx hex show <cell_id> --radius 1 --include-parent` adds parent membership
  context for the selected cell
- `hx hex watch <cell_id> --radius 1` opens a live mini-TUI that redraws the
  neighborhood and streams recent audit runs and events into side panels
- `hx hex parent show <parent_id>` renders the coarse-grained parent hex group
- `hx hex parent watch <parent_id>` opens a live parent-focused mini-TUI with
  neighboring parents, risky boundary ports, and summary panels
- `hx memory summarize` refreshes restart-ready summaries in `.hx/state/`
- `hx resume` loads the compacted repo restart context

Validate the shipped example benchmark battery from the `hx` source checkout:

```bash
hx benchmark validate /absolute/path/to/hx/examples/benchmark_battery.json
```

If a commit is denied, the next step is usually one of four things: re-stage the
patch, collect or verify missing proof, obtain approval for a breaking or
high-risk change, or justify a radius expansion before trying again.

Parent groups are additive in `0.1.x`: they improve summarization, watch views,
MCP context, and reporting, but cell/radius authorization still remains the
only execution boundary.

See [docs/adoption.md](docs/adoption.md) for the golden path, then
[docs/hex.md](docs/hex.md), [docs/contracts.md](docs/contracts.md),
[docs/metrics.md](docs/metrics.md), [docs/memory.md](docs/memory.md),
[docs/benchmarking.md](docs/benchmarking.md),
[docs/security.md](docs/security.md), [docs/codex.md](docs/codex.md),
[docs/gemini.md](docs/gemini.md), [docs/release.md](docs/release.md),
[docs/roadmap.md](docs/roadmap.md), [BENCHMARK.md](BENCHMARK.md),
[CHANGELOG.md](CHANGELOG.md), and [plan.md](plan.md).
