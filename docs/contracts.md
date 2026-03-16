# Port Contracts

A port is the explicit contract between neighboring cells.

Each port records:

- directionality
- declared or extracted surface
- invariants
- compatibility rules
- proof obligations
- approval requirements

Breaking surface changes require proof and, by default, human approval before
commit.

In `release` mode, `hx` can also require human approval for compatible changes
when they cross a high-risk port according to entropy, churn, pressure, and
recent failure history.

Replay guarantee boundary:

- replay is best-effort and permission-preserving
- replay reuses the original run's cell and radius context when present
- replay must not broaden command or path permissions relative to the recorded
  run
- replay failures should be interpreted as safety-preserving refusals, not as
  proof that the original run was invalid

## Proof Tiers

`hx` currently escalates proof obligations in three tiers:

- `standard`: declared per-port checks only
- `elevated`: used for breaking or otherwise escalated port changes; adds
  touched-cell and neighbor-cell tests plus governance artifacts
- `strict`: used for high-risk release-mode changes; adds the elevated checks
  plus a dedicated risk report artifact

Current guarantee boundaries:

- `standard` guarantees only the port-declared proof surface
- `elevated` guarantees that touched and neighbor cells participate in proof
  collection and that governance artifacts are produced
- `strict` guarantees the elevated behavior plus a risk-report artifact for
  release-mode review

These tiers are operational guarantees, not calibrated confidence statements.

## Governance Artifacts

When proof escalation is active, `hx` generates artifacts under
`.hx/artifacts/<task_id>/`, including:

- `port_check.json`
- `surface_diff.json`
- `risk_report.json` for strict-tier changes

Each governance artifact now uses a versioned envelope with:

- `schema_version`
- `artifact_kind`
- `task_id`
- `compatibility`
- `payload`

Current schema version:

- `hx.governance.v1`

Artifact kinds:

- `port_check`
- `surface_diff`
- `risk_report`

Compatibility guarantee:

- additive fields are allowed within a schema version
- removing or renaming required fields requires a schema-version bump
- proof verification rejects unsupported schema versions
- proof verification rejects malformed governance artifacts even if the file
  exists at the required path

## Contract Migration Guidance

When changing a port contract or a governance artifact schema:

- update the contract docs and release notes in the same change
- state whether the change affects enforcement, reporting, or both
- preserve additive compatibility within a schema version whenever possible
- bump schema semantics explicitly when required fields are removed or renamed
- include migration notes when adopters need to update policies, prompts, or
  tooling

## Obligation Weights

`hx` now classifies proof obligations so proof coverage can be reported with
weighted semantics instead of simple item counts.

- `port_declared_check`: `1.0`
- `cell_escalation_check`: `1.25`
- `port_declared_artifact`: `0.75`
- `governance_artifact`: `0.5`
- `risk_report_artifact`: `0.75`

These weights are heuristic governance weights, not calibrated statistical
confidence weights.
