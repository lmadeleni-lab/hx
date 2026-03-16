# Benchmarking

`hx benchmark validate` checks battery structure, and `hx benchmark run`
compares a baseline condition and a treatment condition over the same task
battery.

## Goal

The benchmark harness is designed to measure governance effects, not to claim
model superiority.

Current benchmark output is:

- paired
- repeat-aware
- variance-aware
- descriptive, not inferential

## Task Battery Format

Each task in the battery JSON should include:

- `task_id`
- `difficulty`
- `description`
- `seed_branch`
- `repeats`
- `baseline_commands`
- `treatment_commands`
- `acceptance_checks`

Optional fields:

- `baseline_run_ids`
- `treatment_run_ids`

Use `baseline_run_ids` and `treatment_run_ids` when you want benchmark reports
to summarize real `hx` metrics such as locality and proof coverage from
recorded audit runs.

The shipped example battery is a starter battery, not a canonical benchmark
suite. It is meant to show how to structure:

- a cell-local task
- a boundary-sensitive task
- a conceptual proof-aware task

## Example

```json
[
  {
    "task_id": "bench-1",
    "difficulty": "easy",
    "description": "smoke task",
    "seed_branch": "main",
    "repeats": 2,
    "baseline_commands": ["python3 -c 'print(1)'"],
    "treatment_commands": ["python3 -c 'print(2)'"],
    "acceptance_checks": ["python3 -c 'print(3)'"],
    "baseline_run_ids": ["run-a", "run-b"],
    "treatment_run_ids": ["run-c", "run-d"]
  }
]
```

The repository also ships an example battery at
`examples/benchmark_battery.json`.

## Reported Quantities

Current benchmark reports include:

- success rate
- tool-call count
- duration
- paired deltas for those quantities
- confidence margins when `repeats >= 2`
- locality summaries when audit-run metrics are supplied
- proof-coverage summaries when audit-run metrics are supplied

## Interpretation Rules

- treat current output as descriptive evidence
- do not describe current benchmark deltas as statistically significant
- do not compare policy scores as if they were calibrated predictors
- prefer component metrics over a single heuristic score when explaining why
  one condition behaved differently

## Current Limitations

- benchmark reports do not yet estimate calibrated failure probability
- baseline simulation is still command-driven rather than model-driven
- repeated runs improve stability reporting, but they do not by themselves make
  the benchmark inferential
- the shipped example battery is intentionally small and should be expanded over
  time with richer multi-cell and approval-sensitive tasks
