# Metrics

`hx` computes architecture-aware metrics from staged tasks and audit history.

Current interpretation boundary:

- `port_entropy` is `Normalized`
- all other metrics currently reported by `hx` remain `Heuristic`
- heuristic metrics are useful for governance and comparison inside one repo,
  but they are not calibrated predictors
- benchmark reports should therefore treat these values as descriptive signals,
  not inferential evidence

Metric maturity in the current MVP:

- `port_entropy`: `Normalized`
- `port_churn`: `Heuristic`
- `boundary_pressure`: `Heuristic`
- `proof_coverage`: `Heuristic`
- `architecture_potential`: `Heuristic`
- `policy_risk_score`: `Heuristic`
- `locality`: `Heuristic`
- `propagation_depth`: `Heuristic`
- all parent-level rollups: `Heuristic`

## Port Churn

`hx` now reports churn in two forms:

- `port_churn`: time-decayed churn
- `port_churn_raw`: raw change count

The default decay model is:

`churn_t = sum(exp(-lambda * age_i))`

with a default 30-day half-life:

`lambda = ln(2) / 30`

Migration note:

- historical `port_churn` values produced before this change were raw counts
- current `port_churn` values are recency-weighted and are not directly
  comparable to earlier `port_churn` values
- use `port_churn_raw` for raw-count continuity across versions

## Port Entropy

Normalized Shannon entropy over observed change categories:

- `add_export`
- `remove_export`
- `change_signature`
- `change_schema`
- `change_invariant`
- `change_tests_required`

`hx` now reports `port_entropy` on a normalized `[0,1]` scale using:

`H_norm = H / log2(K)` where `K = 6`

`port_entropy_raw` is also preserved for migration and audit readability.

Migration note:

- historical `port_entropy` values produced before this change are not directly
  comparable to current `port_entropy`
- old values were raw Shannon entropy
- new values are normalized Shannon entropy
- compare cross-version histories using `port_entropy_raw` if raw continuity is
  required

## Boundary Pressure

`boundary_pressure` is now defined as a graph-cut quantity over the active cell
set for a task.

Current implementation:

- active set = `allowed_cells` when available, otherwise `touched_cells`
- pressure = count of neighbor-slot crossings from active cells to inactive
  cells

This is a structural boundary metric rather than the previous blended heuristic.

Migration note:

- historical `boundary_pressure` values produced before this change are not
  directly comparable to current `boundary_pressure`
- old values were a weighted heuristic over cross-cell touches, radius, and
  import pressure
- current values are graph-cut-based
- `boundary_pressure_heuristic` is preserved for transition readability

## Proof Coverage

`hx` now reports proof coverage in two forms:

- `proof_coverage`: obligation-weighted proof coverage
- `proof_coverage_raw`: raw item-count proof coverage

Current obligation classes and weights:

- `port_declared_check`: `1.0`
- `cell_escalation_check`: `1.25`
- `port_declared_artifact`: `0.75`
- `governance_artifact`: `0.5`
- `risk_report_artifact`: `0.75`

Migration note:

- historical `proof_coverage` values produced before this change were simple
  item-count ratios
- current `proof_coverage` values are obligation-weighted and are not directly
  comparable to earlier `proof_coverage`
- use `proof_coverage_raw` for count-based continuity across versions

## Architecture Potential

`architecture_potential` is a repo-health potential function intended to
approximate structural cost or architectural "energy" on a `[0,1]` scale, where
higher values indicate greater boundary stress or coordination burden.

Current implementation is heuristic and combines:

- normalized boundary pressure
- normalized port entropy
- normalized port churn
- normalized propagation depth
- approval requirement rate
- normalized proof burden

Current task-level weights:

- boundary pressure: `0.30`
- port entropy: `0.20`
- port churn: `0.15`
- propagation depth: `0.15`
- approval rate: `0.10`
- proof burden: `0.10`

Current normalization scales:

- boundary pressure scale: `6.0`
- port churn scale: `3.0`
- proof burden scale: `4.0`
- propagation depth scale: `radius / (1 + radius)`

Repo-level reporting currently uses the mean task potential across recorded
runs, plus averaged component values in `architecture_potential_components`.

Interpretation note:

- this metric is heuristic, not calibrated
- its weights and scales are policy-chosen and intended for governance
  visibility, not predictive claims
- compare changes in this metric directionally unless and until calibration work
  is completed

## Parent-Level Rollups

`hx` now reports heuristic parent-level rollups over the coarse-grained
`parent_groups` topology. These metrics are governance-facing summaries over the
child graph; they do not replace child-level enforcement signals.

Current parent metrics:

- `parent_boundary_pressure`: count of cross-parent boundary ports
- `parent_port_pressure`: summed child-port pressure across the parent boundary
- `parent_churn`: summed time-decayed churn across boundary ports
- `parent_entropy`: mean normalized entropy across boundary ports
- `parent_architecture_potential`: heuristic parent-scale structural burden
- `parent_cohesion`: internal-vs-external edge ratio for member cells
- `parent_summary_stability`: reserved heuristic slot for future summary-drift
  tracking

Interpretation boundary:

- these are all `Heuristic`
- they are aggregate rollups over child-level evidence
- they are useful for planning, summarization, watch dashboards, and reporting
- they should not yet be treated as independent policy gates or calibrated
  predictors

## Policy Risk Score

`policy_risk_score = 0.35 * entropy + 0.25 * churn + 0.25 * pressure + 0.15 * recent_failures`

Current interpretation:

- `entropy` is normalized entropy
- `churn` is time-decayed churn
- this score remains heuristic and policy-oriented, not calibrated
- `policy_risk_score` is used for enforcement thresholds such as
  `strict_risk_threshold`
- descriptive reporting should prefer the component metrics (`entropy`, `churn`,
  `pressure`, `recent_failures`) over the policy score alone
