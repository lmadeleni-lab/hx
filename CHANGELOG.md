# Changelog

All notable changes to `hx` will be recorded in this file.

## [0.2.0] — 2026-03-17

### Security

- **Command injection prevention**: `command_allowed()` now rejects commands
  containing shell operators (`;`, `|`, `&&`, `||`, backticks, `$()`).
  Previously, `pytest && rm -rf /` would pass if `pytest` was in the allowlist.
- **Removed `--unsafe-paths`** from `git apply` in temp directory operations.
- **Expanded copy exclusions**: `_copy_repo()` now excludes `.env`, `.env.*`,
  `secrets/`, `.secrets/`, `node_modules/`, `*.pem`, `*.key` when creating
  temp directories for surface diffing.
- **Disabled symlink following** in `shutil.copytree` calls to prevent symlink
  traversal attacks.

### Added

- **Multi-language surface extraction**: TypeScript/JavaScript (`.ts`, `.tsx`,
  `.js`, `.jsx`, `.mjs`) and Go (`.go`) files now have export/signature
  extraction via regex-based analyzers. Python extraction unchanged. Extensible
  via `SURFACE_EXTRACTORS` registry dict. Unsupported file extensions are
  tracked in the surface result.
- **Configurable risk weights**: `policy_risk_score()` accepts optional
  `weights` parameter. Weights can be configured in POLICY.toml under
  `[risk_weights]` with keys: `entropy`, `churn`, `pressure`, `failures`.
- **`py.typed` marker**: Package is now PEP 561 compliant for downstream
  type checking.
- **`HexMap.has_cell()`**: Convenience method for checking cell existence.

### Fixed

- **O(1) cell lookup**: `HexMap.cell()` now uses a `dict` index built at load
  time instead of linear scan. Significant performance improvement for large
  hexmaps.
- **Audit file locking**: `append_event()`, `update_run()`, and `finish_run()`
  now use `fcntl.flock()` for advisory locking to prevent lost-update race
  conditions under concurrent MCP tool calls.
- **Atomic audit writes**: `save_run()` now writes to a `.tmp` file and renames
  into place to prevent partial writes on crash.
- **`TaskState.from_dict()` crash**: No longer crashes on unknown keys in
  serialized JSON. Filters to known dataclass fields, enabling forward
  compatibility with future schema additions.
- **`repo_root()` directory walking**: Now walks up the directory tree to find
  `.hx` or `.git` markers instead of just resolving the current path.

### Changed

- **Default risk weights** are now exposed as `DEFAULT_RISK_WEIGHTS` constant
  in `metrics.py` and documented in POLICY.toml.

## [0.1.1] - 2026-03-17

### Fixed

- Single-cell repositories built via `hx hex build` no longer use a root glob that
  excludes top-level files like `HEXMAP.json` (avoids "outside hexmap" catch-22).
- `repo.stage_patch` now normalizes and validates staged patches into `git apply`
  compatible unified diffs, preventing `port.check` failures like "No valid patches
  in input" when an agent provides apply_patch-style text.

### Changed

- enforcement-facing thresholds now use `policy_risk_score`
- descriptive reporting now emphasizes component metrics over a single policy
  score
- README and release docs now describe the supported clean-install path rather
  than implying editable mode is the primary user install flow
- benchmark docs and shipped examples now distinguish starter batteries from
  stronger future evaluation suites

## [0.1.0] — Initial MVP

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
