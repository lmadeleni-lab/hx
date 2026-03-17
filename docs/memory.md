# Memory and Context Compaction

`hx` treats memory as a layered system rather than a single transcript log.

## Storage Model

`hx` keeps:

- durable project memory in the repo itself
  - `plan.md`
  - `AGENTS.md`
  - `HEXMAP.json`
  - `POLICY.toml`
- raw operational history in `.hx/`
  - audit runs
  - proof artifacts
  - staged tasks
  - replay inputs
- compacted derived summaries in `.hx/state/`

Current state files:

- `.hx/state/repo_summary.json`
- `.hx/state/parent_summaries.json`
- `.hx/state/cell_summaries.json`
- `.hx/state/open_threads.json`
- `.hx/state/session_summary.json`

## Compaction Model

Compaction is hierarchical:

1. repo summary
2. parent summaries
3. cell summaries
4. port and artifact drill-down
5. raw audit events on demand

This keeps restart context compact while preserving full raw history for replay,
review, and regeneration.

Important boundary:

- raw audit and artifact storage is append-oriented
- summaries in `.hx/state/` are derived artifacts and may be regenerated
- authorization still remains cell-based even when parent summaries are loaded

## Commands

Generate or refresh derived state:

```bash
hx memory summarize
```

Inspect whether state files exist:

```bash
hx memory status
```

Load the current restart context:

```bash
hx resume
```

## Automatic Refresh

`hx` currently refreshes memory summaries automatically after:

- governed patch commits
- benchmark runs

You can still run `hx memory summarize` explicitly whenever you want to refresh
the derived state after manual edits or exploratory work.
