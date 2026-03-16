# Changelog

All notable changes to `hx` will be recorded in this file.

The format is intentionally simple while the project is pre-1.0.

## [Unreleased]

### Added

- hex-aware CLI commands for init, validation, logging, replay, and benchmarking
- MCP stdio server with end-to-end client validation
- staged proof-carrying patch workflow with approval gates
- normalized entropy, time-decayed churn, graph-cut boundary pressure, weighted
  proof coverage, and architecture potential reporting
- versioned governance artifact schemas with proof-time validation
- paired benchmark reporting with repeat-aware variance and audit-backed metric
  summaries
- clean-install package smoke coverage in CI
- release and adoption docs that describe the intended `0.1.0` public contract

### Changed

- enforcement-facing thresholds now use `policy_risk_score`
- descriptive reporting now emphasizes component metrics over a single policy
  score
- README and release docs now describe the supported clean-install path rather
  than implying editable mode is the primary user install flow
- benchmark docs and shipped examples now distinguish starter batteries from
  stronger future evaluation suites
