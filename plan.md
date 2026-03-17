# hx Execution Plan

This document is the working execution plan for `hx`. It is the primary
delivery contract for maintainers and coding agents. It is intentionally more
operational and implementation-precise than the README.

## 1. Mission

Build `hx` into a publishable open-source local agentic coding harness whose
governing model is:

- hexagonal cell locality
- explicit port contracts
- proof-carrying diffs
- safe-by-default execution
- auditability and replay
- measurable architectural health

The project must remain small enough to trust, strict enough to govern agent
behavior, and clear enough to adopt in real repositories.

## 2. Product Thesis

`hx` is not a model client. It is a harness that sits between an agent CLI and a
repository.

Core consequences:

- the harness must enforce repository discipline even when the agent does not
- all operations must be contextualized by `active_cell_id` and `context_radius`
- cross-cell changes must be interpretable as port interactions, not ad hoc file
  access
- boundary changes must produce evidence, not just output
- the audit story must be strong enough to support replay, review, and future
  benchmarking

## 3. End State

The near-term end state is a stable MVP that can be published and then evolved
without architectural rework.

Success criteria:

- a new repository can install `hx`, run `hx init`, generate a starter hex map,
  start the MCP server, and perform a scoped staged patch flow
- the supported first-release host target is explicit and tested rather than
  assumed; for `0.1.x`, that target is macOS terminal sessions
- unsafe operations are denied by default with strong error messages
- boundary changes are observable through `port.check`, proof collection, and
  audit logs
- metrics can identify risky ports and quantify whether `hx` is improving
  locality and interface stability
- the repository is ready for external contributors, CI, docs review, and
  benchmark iteration

## 4. Operating Principles

These principles govern all implementation work.

1. Enforce before you explain.
2. Prefer small kernel code over feature sprawl.
3. Keep policy explicit and repo-local.
4. Treat radius expansion as an exception that must be justified.
5. Make denial reasons actionable and machine-readable where possible.
6. Never bypass the staged patch flow for convenience.
7. Preserve deterministic artifacts whenever behavior matters.
8. Benchmark the harness itself, not just task output.

## 4.1 Agent Operating Model

The project uses a small specialist crew rather than a single undifferentiated
agent posture.

Required specialists:

- Principal Engineer / Systems Architect: owns sequencing, architectural
  integrity, and alignment to this plan
- Code Reviewer Agent: stress-tests correctness, regression risk, enforcement
  quality, and test sufficiency
- PhD Mathematician Agent: validates metrics, scoring, entropy, churn,
  pressure, benchmark logic, and quantitative claims

Crew usage rules:

- implementation changes with architectural consequences must receive Code
  Reviewer scrutiny before being considered complete
- any metric, risk-scoring, entropy, benchmark, propagation, normalization, or
  threshold change must receive PhD Mathematician scrutiny before being treated
  as trustworthy
- specialist review must happen early enough to influence design, not only late
  enough to comment on it

## 4.2 Mathematical Foundations and Formalization Roadmap

`hx` currently implements enforceable governance using operational heuristics
and explicit policy rules. The long-term target is a graph-governed,
quantitatively calibrated system. This distinction must remain explicit in code,
docs, benchmark reports, and public claims.

### Current State

- `hx` currently uses operational heuristics for entropy, churn, boundary
  pressure, proof coverage, locality, propagation depth, and risk
- these heuristics are acceptable for MVP governance because they are observable,
  auditable, and immediately useful for enforcement
- these heuristics are not yet mathematically calibrated estimators
- public claims must treat current metrics as structural signals and governance
  aids, not as statistically validated predictors
- current thresholds are policy-chosen unless explicitly marked otherwise

### Formal Model Target

Repository topology target:

- model the repository as a graph `G = (V, E)`
- each cell is a vertex `v in V`
- each port is a directed edge `e in E` with an associated contract, proof
  obligations, compatibility semantics, and approval policy

Locality target:

- locality is graph distance from the active cell
- radius scope is the closed ball `B(v, r)` around active cell `v`
- allowed cells for a task are exactly the vertices in `B(v, r)` unless policy
  grants an explicit, logged exception

Propagation target:

- propagation depth is the minimum radius required to restore acceptance checks
  for a task after failures or port effects are observed

Boundary target:

- the activated boundary for a task is the cut between allowed cells and
  disallowed cells
- boundary-oriented metrics should converge toward cut-based formulations rather
  than purely ad hoc weighted counters

### Metric Formalization Targets

The following formulations are the mathematical targets for future
implementation. Each target must be tracked with an explicit maturity state.

- normalized entropy:
  `H_norm = H / log2(K)` where `K` is the number of change categories
  Status: `Implemented`
- time-decayed churn:
  `churn_t = sum(exp(-lambda * age_i))`
  Status: `Implemented`
- graph-cut boundary pressure:
  weighted cut over the active set boundary
  Status: `Partially Implemented`
- weighted proof coverage:
  satisfied obligation weight divided by total required obligation weight
  Status: `Implemented`
- repo-level architecture potential:
  a scalar function over entropy, pressure, propagation depth, approval rate,
  proof burden, and related structural costs
  Status: `Implemented`
- heuristic risk score:
  current weighted policy score derived from entropy, churn, pressure, and
  recent failures
  Status: `Implemented`, pending calibration

### Quantitative Governance Principle

- compatibility and risk are independent axes
- compatible changes may still require approval or strict proof
- breaking classification must remain semantic and contract-oriented
- risk may remain heuristic in the short term and probabilistic only after
  calibration work is complete
- governance logic must not conflate “breaking” with “high-risk”

## 5. Current Baseline

As of this revision, the repository already contains:

- Python packaging and `hx` CLI
- `hx init`, `hx hex build`, `hx hex validate`, `hx mcp serve`, `hx doctor`,
  `hx log`, `hx replay`, `hx benchmark run`, `hx benchmark report`
- derived parent hex groups inside `HEXMAP.json` for coarse-grained topology,
  summarization, and operator visibility
- MCP tools, resources, and prompts for hex, ports, repo ops, proof, commands,
  tests, and metrics
- staged patch storage, proof hooks, audit storage, basic replay, metrics, and
  risk scoring
- starter docs, CI, and tests including a smoke path

This is the foundation, not the finish line.

### Known Mathematical Limitations

- entropy is normalized but not calibrated against downstream regression risk
- churn is time-decayed but still governed by a policy-chosen decay parameter
- boundary pressure is graph-cut-based but not yet weighted into a richer cut
  model
- proof coverage is obligation-weighted but its weight schedule remains
  heuristic rather than empirically fit
- architecture potential is implemented as a heuristic potential function with
  policy-chosen weights and scales, not a calibrated health estimator
- risk score is currently hand-weighted, not calibrated from observed
  regressions
- benchmark methodology now supports repeated paired runs and confidence
  margins, but it remains descriptive rather than inferential

## 6. Workstreams

The project advances through the following parallel but coordinated workstreams.

### A. Kernel and Safety

Goal:

- make the authorization, policy, port-check, proof, commit, and audit pipeline
  precise and difficult to circumvent

Primary tasks:

- harden policy parsing and validation
- tighten path authorization semantics for reads, searches, commands, and tests
- ensure commit-time invariants are re-checked, not assumed from earlier stages
- make denial classes explicit and structured
- ensure replay never executes disallowed commands
- add resource caps and failure-safe cleanup everywhere staging or temp copies
  occur

### B. Hex and Port Semantics

Goal:

- improve the truthfulness of cells, neighbors, and ports so governance maps to
  real repository architecture

Primary tasks:

- improve `hx hex build` heuristics so starter cell assignment is less noisy
- add and validate coarse-grained parent hex groups without weakening
  cell/radius authorization
- support manual refinement workflows without fighting generated output
- add stronger validation for symmetry, null side semantics, and missing tests
- improve surface extraction heuristics for Python and declared-surface fallback
- formalize breaking vs non-breaking classification rules

### C. Proof-Carrying Diffs

Goal:

- ensure boundary-affecting changes produce evidence proportional to risk

Primary tasks:

- enrich proof obligations at the port level
- add artifact normalization and storage conventions
- attach proof metadata consistently to audit runs
- support human approval markers for breaking changes and policy-gated changes
- ensure commit denial reasons identify the specific missing proof or gate

### D. Metrics and Governance

Goal:

- turn architectural health into measurable, reviewable signals

Primary tasks:

- formalize metric definitions before reweighting them
- normalize entropy so it becomes comparable across ports and repositories
- replace raw churn counts with recency-sensitive decay
- replace heuristic boundary pressure with a cut-based formulation over
  activated cells
- convert proof coverage from count-based to obligation-weighted coverage
- preserve the current heuristic risk score for policy gating until a calibrated
  model exists
- collect enough history to support future calibration of regression likelihood
- separate “policy score used for enforcement” from “validated predictive score
  used for claims”
- require PhD Mathematician review for any change to formulas, thresholds,
  normalization, or benchmark interpretation

Governance Rule:

- no metric rewrite may be merged unless the plan states whether the change
  affects enforcement, public interpretation, or both

### D2. Mathematical Rigor and Model Calibration

Goal:

- convert current metric heuristics into a mathematically explicit and eventually
  calibrated framework without weakening safe current behavior

Primary tasks:

- convert repository and radius semantics into explicit graph terminology
  throughout the project
- define which quantities are structural invariants, which are heuristics, and
  which are estimated statistics
- design a calibration path from heuristic risk scoring to fitted
  failure-probability estimation
- define benchmark methodology with repeated trials, paired comparisons, and
  confidence reporting
- prevent benchmark reports from overstating significance before calibration is
  complete

### E. MCP Integration

Goal:

- make `hx` a clean, reliable MCP kernel for Codex CLI and Gemini CLI

Primary tasks:

- validate tool schemas and naming stability
- test stdio flow with an external MCP client harness
- harden prompt guidance for disciplined cell/radius workflows
- ensure resources are useful for real agent context loading
- document transport configuration clearly and keep parity across clients

### F. Benchmarking and Evaluation

Goal:

- prove that `hx` improves development outcomes relative to less-governed flows

Primary tasks:

- define a realistic task battery format and sample battery
- improve baseline simulation so it is fair but meaningfully unconstrained
- track success rate, regressions, time-to-green, approvals, overrides, and
  proof coverage
- compare locality and port stability outcomes across runs
- emit markdown reports suitable for public sharing

### G. Publishability and Community Readiness

Goal:

- make the project understandable and trustworthy to external adopters

Primary tasks:

- deepen architecture docs and examples
- add a real SECURITY posture and threat-model examples
- improve contributor guidance for adding ports, proofs, and metrics
- prepare a roadmap section and public issue templates later
- maintain naming, formatting, and repository hygiene suitable for first release
- keep the agent crew model documented so contributors know when reviewer and
  mathematician scrutiny is expected

## 7. Phase Plan

### Phase 1. Stabilize the MVP

Objectives:

- eliminate correctness gaps in the current core
- increase confidence in authorization, proof, commit, and audit interactions

Exit criteria:

- all current CLI and MCP flows are covered by tests
- staged patch workflow is robust under common failure modes
- replay, metrics, and log outputs are internally consistent

Status:

- substantially complete, with residual hardening items carried into later
  phases
- completed this cycle:
  - added denial-path coverage for path sandbox and out-of-radius access
  - added command allowlist denial coverage
  - added breaking port change approval enforcement and approval flow support
  - added release-mode high-risk approval enforcement for compatible changes
  - added proof-verification denial coverage at commit time

Corrective Actions Identified During Phase 1:

- normalize command execution for proof-time checks through the active
  interpreter
- ensure authorization happens before reading during search flows
- keep approval requirement separate from compatibility classification
- make denial-path tests mandatory for new enforcement logic
- treat “proof obligation collection succeeded” and “proof verification
  succeeded” as separate conditions

Residual carry-forward work:

- add more negative tests for denial cases that remain unmodeled
- verify metrics persistence semantics across multiple tasks and runs
- harden replay failure-path visibility without widening permissions

### Phase 2. Harden Governance

Objectives:

- make ports and proofs feel like first-class control planes rather than
  metadata containers

Exit criteria:

- port classification is explainable
- proof obligations can be escalated by risk and mode
- release mode meaningfully tightens boundaries

Status:

- in progress
- completed this cycle:
  - introduced proof tiers: `standard`, `elevated`, and `strict`
  - escalated proof checks from touched and neighbor cells for elevated and
    strict port changes
  - generated governance artifacts for port checks, surface diffs, and strict
    risk reports
  - persisted approval decisions into audit data
  - normalized proof-time command execution so `pytest` and `ruff` run through
    the active Python interpreter
  - converted proof coverage to an obligation-weighted metric with explicit
    obligation classes and weights
  - formalized governance artifact schemas, compatibility envelopes, and
    verification behavior

Corrective Actions Identified During Phase 2:

- generated governance artifacts must be treated as first-class proof artifacts,
  not incidental files
- approval decisions must persist into audit state with enough detail for replay
  and review
- proof tiers must remain orthogonal to compatibility classification
- release-mode strictness must be documented as a mode behavior, not inferred
  only from code
- proof escalation must not assume tool names are directly executable from
  `PATH`

Phase 2 Precision Gap Still Open:

- proof tiers are implemented operationally and reflected in weighted proof
  coverage, but their weight schedule remains policy-chosen rather than
  calibrated
- risk escalation exists, but its threshold is heuristic rather than calibrated
- governance artifacts are versioned and validated, but schema-evolution policy
  still needs deeper release documentation

Remaining key tasks:

- human approval representation and persistence semantics refinement
- migration-oriented prompts and contract-change docs
- formal statement of what each proof tier guarantees

### Phase 3. Improve Architectural Signal

Objectives:

- move from basic metrics to actionable governance intelligence grounded in
  mathematically explicit definitions

Exit criteria:

- mathematically defined metrics are documented and implemented
- all reportable metrics specify whether they are heuristic, normalized, or
  calibrated
- at least one repo-level aggregate health function exists and is tracked over
  time

Key tasks:

- normalize entropy to a stable `[0,1]` range
- implement time-decayed churn with an explicit decay parameter
- redesign boundary pressure as a graph-cut measure over active vs inactive
  cells
- define weighted proof coverage using obligation classes and weights
- define and implement repo-level architecture potential
- separate enforcement metrics from explanatory and reporting metrics
- define confidence and uncertainty language for benchmark and governance outputs

Completed this cycle:

- normalized entropy and preserved raw entropy for historical continuity
- implemented time-decayed churn with a default half-life and raw-count
  continuity
- redesigned boundary pressure around active-set graph cuts while preserving
  the old heuristic for migration readability
- implemented weighted proof coverage and preserved raw count-based coverage
- introduced a repo-level architecture potential function and component
  breakdowns for audit and reporting
- added property-based and invariant tests for radius monotonicity,
  authorization monotonicity, and replay command-set safety
- separated enforcement-facing `policy_risk_score` semantics from descriptive
  reporting metrics in code and docs

### Phase 4. External Integration and Benchmark Credibility

Objectives:

- prove `hx` works in realistic agent loops and publish evidence without
  overstating certainty

Exit criteria:

- documented external MCP integrations are verified
- benchmark methodology is reproducible
- report outputs distinguish observed deltas from statistically supported
  conclusions

Key tasks:

- end-to-end client integration checks
- paired baseline and treatment runs on the same task seeds
- repeated runs where stochasticity can affect outcomes
- confidence intervals or equivalent uncertainty reporting in benchmark
  summaries
- variance reporting for time-to-green, locality, and proof coverage
- explicit warning language when a report is descriptive but not inferential

Completed this cycle:

- benchmark runs are now explicitly paired across baseline and treatment
  conditions
- repeated runs are supported per task
- confidence margins and variance are reported when repeat counts support them
- benchmark reports now include explicit descriptive-only warning language
- benchmark reports can now summarize locality and proof-coverage variance from
  recorded audit-run metrics rather than command-level proxies alone
- external MCP stdio integration is now validated end to end with a real client
  session covering initialize, tool discovery, tool execution, resource reads,
  and prompt retrieval
- benchmark batteries can now be validated explicitly, and the repo ships an
  example battery for adopters to extend

### Phase 5. Pre-Release Readiness

Objectives:

- remove rough edges that would hurt trust at first public exposure

Exit criteria:

- docs, examples, CI, and security posture are coherent
- versioning and release process are obvious

Key tasks:

- changelog and release notes strategy
- semantic versioning policy
- example adopter repository walkthrough
- explicit statement of metric maturity in public docs

Completed this cycle:

- added `CHANGELOG.md` and an explicit release policy
- added an adopter walkthrough and roadmap docs
- added public issue templates for bugs and feature requests
- updated public docs to reflect current metric maturity and benchmark guidance
- implemented parent hex groups as a second topology layer inside `HEXMAP.json`
- added parent-aware CLI, MCP resources/tools/prompts, and live parent watch
  dashboards
- added heuristic parent rollup metrics, summaries, and scheduler/reporting
  hooks while keeping cell-based authorization primary
- added native Codex onboarding commands so `hx` can configure MCP setup and
  guide users into the `codex --login` flow without requiring manual config
- added a first memory/context-compaction foundation under `.hx/state/` with
  repo, parent, cell, open-thread, and session summaries plus `hx resume`

## 8. Strategy When Issues Arise

Problems are expected. The goal is not to avoid them, but to respond without
eroding the architectural thesis.

### If an implementation shortcut conflicts with the model

Strategy:

- do not paper over the mismatch
- either redesign the implementation to respect cells, ports, proofs, and audit
  constraints, or mark the gap explicitly as temporary debt

Rule:

- model integrity beats short-term convenience

### If the enforcement logic blocks legitimate work

Strategy:

- improve explainability first
- inspect whether the policy, hexmap, or port contract is inaccurate
- only widen behavior if the model is genuinely too narrow, not because the
  denial is inconvenient

Rule:

- false positives should be reduced, but not by weakening guarantees blindly

### If metrics look noisy or misleading

Strategy:

- treat metric quality as a product issue
- preserve raw events and adjust derived computations
- never hide instability by dropping data silently
- escalate to PhD Mathematician review before changing public claims or
  thresholds

Rule:

- better imperfect visible metrics than overfit invisible ones

### If a metric is operationally useful but mathematically weak

Strategy:

- keep it if it is clearly labeled heuristic
- prohibit presenting it as predictive or calibrated
- add a plan item for normalization or calibration rather than silently treating
  it as settled

Rule:

- operational utility does not justify mathematical overstatement

### If formalization and implementation conflict

Strategy:

- preserve the current safe behavior
- record the formal target separately
- do not simplify the model description merely to match an expedient
  implementation

Rule:

- current implementation convenience must not redefine the long-term model

### If replay diverges from original behavior

Strategy:

- mark replay as best-effort
- log the exact divergence point
- improve artifact capture or determinism around that class of action

Rule:

- replay must fail clearly, not pretend success

### If external MCP clients behave inconsistently

Strategy:

- narrow the problem to transport, schema, prompt use, or tool semantics
- keep the kernel behavior stable and adapt the integration layer deliberately

Rule:

- client quirks must not leak unnecessary complexity into the kernel

### If security and usability conflict

Strategy:

- stay deny-by-default
- add explicit, documented escape hatches only when they are auditable and
  policy-gated

Rule:

- invisible bypasses are unacceptable

### If reviewer and implementer disagree

Strategy:

- prefer the smallest change that preserves architectural guarantees
- reproduce the disagreement with a test, proof artifact, benchmark sample, or
  explicit counterexample
- escalate quantitative disputes to the PhD Mathematician and enforcement or
  regression disputes to the Code Reviewer

Rule:

- disagreements must resolve through evidence, not by overriding concerns

## 9. Decision Framework

When there are multiple implementation options, choose using this order:

1. Does it preserve the cell, port, proof, and audit model?
2. Is it safe by default?
3. Is it mathematically honest about what is heuristic versus calibrated?
4. Is it understandable to adopters and contributors?
5. Is it testable and auditable?
6. Is it dependency-light and operationally simple?
7. Is it extensible without architectural churn?

## 10. Quality Gates

Every meaningful change must be evaluated against these gates.

### Code Gate

- lint clean
- tests green
- new behavior covered at the right layer

### Governance Gate

- cell and radius semantics remain enforced
- port-affecting changes still flow through the staged workflow
- audit and proof data remain attached and inspectable

### Documentation Gate

- README or docs updated if user-facing behavior changed
- plan updated if priorities, sequencing, or strategy changed

### Release Gate

- no undocumented dangerous defaults
- benchmark and metrics stories remain reproducible

### Quantitative Gate

- every metric must state whether it is heuristic, normalized, or calibrated
- every threshold must state whether it is policy-chosen or empirically fitted
- benchmark summaries must not imply significance without repeated-run support
- metric changes must include a migration note if historical comparability is
  affected

## 11. Testing Strategy

Testing must be layered, not just additive.

### Unit Tests

- hexmap loading and validation
- policy parsing and allow or deny logic
- port surface extraction and classification
- metrics calculations and risk scoring
- entropy normalization behavior
- time-decay behavior for churn
- independence of compatibility vs approval requirement
- weighted proof coverage calculation
- graph-radius monotonicity properties

### Integration Tests

- staged patch lifecycle
- proof collection and verification
- MCP server construction and tool-path behavior
- replay and audit readback

### Negative Tests

- unauthorized read, search, or write attempts
- disallowed command execution
- missing proof obligations
- required approval absent for breaking changes
- high-risk compatible changes requiring approval
- proof-tier escalation artifact generation failures
- mismatched historical metric semantics after formula changes
- replay using only originally permitted command forms

### Property-Based and Invariant Tests

- `B(v, r) subseteq B(v, r+1)`
- authorization monotonicity by radius
- approval monotonicity at commit
- replay cannot widen the command set
- compatibility classification remains independent from approval escalation

### Smoke Tests

- initialize repo
- build hex map
- stage trivial patch
- run `port.check`
- collect and verify proof
- commit
- inspect audit and metrics

## 12. Documentation Strategy

The docs should evolve in layers.

Layer 1:

- README quickstart and positioning

Layer 2:

- architecture docs for hex, contracts, metrics, and security

Layer 3:

- integration guides for Codex and Gemini

Layer 4:

- examples, benchmark battery docs, and adoption guides

Every new capability must answer three questions in docs:

- why does this exist
- how do I use it
- what does it prevent or guarantee

Additional documentation rules:

- every metrics doc must define units, scale, and interpretation
- every benchmark doc must distinguish descriptive metrics from calibrated claims
- every governance doc must explain whether a threshold is heuristic or
  empirically justified

## 13. Risk Register

### Risk: the hex model becomes decorative

Mitigation:

- keep authorization and commit logic tied to active cell and radius
- add denial tests whenever a bypass is found

### Risk: ports become too manual to maintain

Mitigation:

- improve heuristics and declared fallback balance
- invest in validation and generated hints

### Risk: proof flow becomes too heavy for normal work

Mitigation:

- scale obligations with risk and mode
- keep R0 and R1 low-friction for safe changes

### Risk: metrics are overclaimed

Mitigation:

- label every metric with a maturity class
- separate heuristic enforcement scores from calibrated explanatory scores
- prohibit inferential benchmark language before calibration work is complete

### Risk: external benchmark claims outrun methodology

Mitigation:

- require repeated trials for any stochastic workflow
- require paired baseline and treatment comparisons
- require uncertainty language in reports

## 14. Maintenance Rules for This Plan

This plan is a living control document.

It must be updated when:

- priorities materially change
- a phase is completed or materially re-scoped
- a new strategic or mathematical limitation appears
- a major implementation corrective action is discovered
- the project thesis or release bar changes

Updates must include:

- what changed
- why it changed
- whether sequencing or scope changed
- whether any metric or threshold changed in meaning

## 14.1 Metric Maturity Model

Metrics must be explicitly classified into one of these maturity classes.

- `Heuristic`
  - policy-useful, operationally observable, not calibrated
- `Normalized`
  - mathematically comparable across contexts, still not necessarily calibrated
- `Calibrated`
  - empirically fit and valid for stronger predictive or comparative claims

Current maturity mapping:

- port entropy: `Normalized`
- port churn: `Heuristic`
- boundary pressure: `Heuristic`
- proof coverage: `Heuristic`
- architecture potential: `Heuristic`
- policy risk score: `Heuristic`
- locality score: `Heuristic`
- propagation depth: `Heuristic`

## 15. Immediate Next Actions

1. Cut the first release candidate using the documented release checklist and
   the completed clean-install rehearsal.
2. Prepare the first public GitHub push with the current `0.1.0` contract,
   issue templates, and benchmark starter materials.
3. Continue the mathematical calibration roadmap for weighted pressure and
   calibrated failure prediction.

## 16. Validation Checklist

This plan revision is only acceptable if all of the following are true:

- every mathematician recommendation is either mapped to a phase or workstream,
  or explicitly deferred with a reason
- every prior-phase corrective action is recorded under the phase where it was
  discovered
- compatibility, approval, and risk are described as separate concepts
- every quantitative term in the plan is labeled as heuristic, normalized, or
  calibrated where relevant
- no section implies that current metrics are statistically validated when they
  are not
- immediate next actions are ordered and implementation-ready
