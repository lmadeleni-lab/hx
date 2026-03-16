# BENCHMARK.md

`hx benchmark validate` checks a task battery before execution, and
`hx benchmark run` consumes a validated JSON task battery and emits
`benchmark_report.md`.

Minimum task fields:

- `task_id`
- `difficulty`
- `description`
- `seed_branch`
- `repeats`
- `baseline_commands`
- `treatment_commands`
- `acceptance_checks`

Optional metric-backed reporting fields:

- `baseline_run_ids`
- `treatment_run_ids`

Guidance:

- use paired baseline and treatment tasks on the same seed branch
- use `repeats >= 2` for confidence margins
- provide audit run ids when you want locality and proof-coverage summaries
- treat the current output as descriptive, not inferential
- validate the battery before running it
- use the shipped example battery as a starter template, not as a claim of
  research-grade coverage

Shipped example:

- `cell-local-smoke`: a cell-local paired smoke task
- `multi-cell-governance-smoke`: a boundary-sensitive starter task
- `proof-aware-governance-smoke`: a conceptual proof/approval-aware starter
  task

See `docs/benchmarking.md` for the full format and reporting rules.
