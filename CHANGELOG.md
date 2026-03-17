# Changelog

All notable changes to `hx` will be recorded in this file.

## [0.11.0] — 2026-03-17

### Added

- **Claude Code native integration**: `hx bootstrap` generates
  `.claude/settings.json` with MCP server auto-discovery config.
- **Gemini CLI integration**: `hx gemini setup` and `hx gemini status`
  commands. Writes MCP entry to `~/.gemini/settings.json`.
- **GEMINI.md**: `hx bootstrap` generates Gemini-specific agent
  instructions derived from live HEXMAP and POLICY.

## [0.10.0] — 2026-03-17

### Added

- **Task planner**: `hx plan create/show/advance` for multi-step work
  across cells with dependency tracking.
- **Sample prompts**: `hx samples` shows 6 task templates with concrete
  `hx run` examples (bug fix, tests, refactor, docs, features, multi-step).
- **Actionable error messages**: authorization failures now explain what
  went wrong and how to fix it (policy violations show denylist,
  cell errors list available cells, API key errors give setup guide).

## [0.9.0] — 2026-03-17

### Added

- **Stateful reasoning engine** (`reasoning.py`): the LLM is now a consultant,
  not the system. hx owns state, simulation, and decision logic.
- **Reasoning gate** (`reasoning_gate()`): evaluates occupation fraction,
  boundary pressure, and port risk to decide LOCAL (deterministic),
  LLM_SCOPED (focused prompt on hot edges), LLM_FULL, or ESCALATE.
  Integrated into the agent loop before each LLM call.
- **Formal state transitions** (`transition_state()`): incremental updates
  with before/after risk snapshots, drift detection, and append-only
  transition log (`.hx/state/transitions.jsonl`).
- **Feedback integrity** (`check_feedback_integrity()`): holonomy check on
  affected subgraph after tool calls to detect accumulated inconsistencies.
- **Transport-cost prompts** (`build_scoped_prompt()`): when reasoning gate
  returns LLM_SCOPED, constructs minimal prompt with only high-cost edges.
- **Percolation monitor** (`percolation_status()`): real-time occupation
  tracking at cell and parent level with phase classification.
- New CLI commands: `hx gate`, `hx percolation`.

## [0.8.0] — 2026-03-17

### Added

- **Mathematician-reviewed hex lattice theory**: percolation threshold tracking
  (p_c=1/2), information-weighted boundary pressure with isoperimetric
  normalization, holonomy/cocycle cycle-consistency checks, graph invariants
  (V, E, components, Euler characteristic), port direction validation enum.
- **Nonlinear architecture potential**: entropy×churn interaction term captures
  compounding risk. All weights sum to 1.0 (proper convex combination).
- **Parent group improvements**: vertex connectivity strength, boundary
  occupation fraction, pooled entropy (Jensen's inequality correct).
- **`graph_invariants()`**: computes topological invariants for tracking
  across hexmap rebuilds.

### Changed

- `policy_risk_score` now normalized to [0,1] with all components bounded.
  Interaction term is inside the weight budget. `strict_risk_threshold`
  default changed from 2.5 to 0.65.
- `boundary_pressure` returns isoperimetrically normalized ratio instead of
  raw cut weight. Uses pairwise edge weights examining both endpoints.
- `validate_hexmap` now runs holonomy checks, dual port validation,
  orientation pairing, and percolation warnings. Connectivity and
  percolation issues are warnings (not hard errors).
- Port direction validated via `__post_init__` — only accepts `none`,
  `export`, `import`, `bidirectional`.

## [0.7.0] — 2026-03-17

### Added

- **`hx readiness`**: 8-point project health check reporting scaffold,
  hexmap, policy, git, tests, audit, risk, and agent config status.
- **`hx suggest`**: analyzes repo and suggests low-risk starter tasks
  sorted by safety with ready-to-run `hx run` commands.

## [0.6.0] — 2026-03-17

### Added

- **Token optimization suite** (6 features):
  - Chunked `repo.read` with auto-truncation at 100KB and offset/limit paging
  - Pre-filtered `repo.search` with cell-path scoping and max 20 results
  - Sparse graph prompt replacing 36 port.describe calls with adjacency_summary
  - Cached surface snapshots in `.hx/state/surfaces.json`
  - Progressive `hex.context` defaulting to summary mode
  - Tool result compression stripping null ports and verbose fields
- **`adjacency_summary()`** for direct hex graph queries without tool calls.
- **Surface cache** rebuilt on commit_patch and hex build.

### Changed

- `repo.read` returns dict with metadata (total_lines, truncated, warning).
- `repo.search` returns dict with matches, total_count, and capped flag.
- `hex.context` defaults to `detail='summary'` (counts + graph).
- Agent system prompt uses sparse graph instead of port.describe loop.

## [0.5.0] — 2026-03-17

### Added

- **`hx setup`**: one-command guided onboarding — auto-detects language,
  scaffolds templates, builds hexmap, validates, suggests policy mode.
- **`hx bootstrap`**: generates `.claude/CLAUDE.md` with project-specific
  governance instructions, `.claude/memory/` with context and rules.
- **Agent memory injection**: system prompt loads risky ports, failed runs,
  pending tasks from `.hx/state/` via `load_memory_context()`.

## [0.4.0] — 2026-03-17

### Added

- **Agent loop** (`agent.py`): orchestrates Claude with hx governance tools,
  streaming output, approval flow, and audit integration.
- **Unified tool registry** (`tools.py`): 40+ tools extracted from MCP server
  into reusable registry shared by MCP and agent loop.
- **Streaming renderer** (`stream.py`): colored terminal output for agent
  execution with text deltas, tool calls, and approval prompts.
- **Status dashboard** (`status.py`): git-status-style governance view.

### Changed

- `mcp_server.py` refactored from ~300 lines to ~40, delegating to ToolRegistry.
- MCP stdio test updated for newer SDK (structuredContent → content).
- Version bumped to 0.4.0.

## [0.3.0] — 2026-03-17

### Added

- Security hardening, multi-language surface extraction, and safe internal
  refactors (merged from PR #2).

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
