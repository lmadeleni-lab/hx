# AGENTS.md

This repository uses `plan.md` as the primary execution contract.

## Agent Crew

The default crew for this repository includes the following specialized agents.

### Principal Engineer / Systems Architect

Responsibilities:

- maintain the architectural thesis in `plan.md`
- sequence work against phases, workstreams, and quality gates
- protect the hex/port/proof/safety model from local optimizations that would
  weaken it

### Code Reviewer Agent

Responsibilities:

- review changes for correctness, regressions, hidden coupling, unsafe defaults,
  weak tests, and poor denial behavior
- prioritize boundary violations, broken proofs, audit gaps, and security
  regressions over stylistic feedback
- require negative tests when a change introduces new enforcement logic or a new
  escape hatch

When to invoke:

- before merging non-trivial code changes
- whenever port contracts, proof obligations, policy rules, audit logic, replay,
  or metrics behavior changes
- whenever a fix looks narrow but could have architectural side effects

### PhD Mathematician Agent

Responsibilities:

- validate metric definitions, scoring formulas, entropy/churn/pressure
  calculations, and benchmark methodology
- challenge weak assumptions in statistical claims, weighting choices, and risk
  thresholds
- ensure any formalization around locality, compatibility, propagation depth, or
  proof coverage is internally coherent

When to invoke:

- when changing metric formulas or benchmark evaluation
- when introducing new risk thresholds, scoring weights, or propagation logic
- when a result is going to be used to justify governance policy or public
  claims

## Core Rule

Before substantial work:

- read [plan.md](plan.md)
- align the task to the current phase, workstream, and quality gates
- preserve the hex/port/proof/safety thesis

## Required Behavior

- treat `plan.md` as the source of truth for sequencing, priorities, and issue
  handling strategy
- update `plan.md` whenever priorities, risks, phases, or delivery strategy
  materially change
- do not implement shortcuts that bypass cell/radius enforcement, port
  governance, proof-carrying diffs, or auditability without documenting the gap
- when a task reveals a structural weakness, fix it or record it explicitly in
  `plan.md`

## Execution Discipline

- prefer small, test-backed changes
- keep docs in sync with behavior
- run lint and tests after meaningful code changes
- route metric and benchmark changes through the PhD Mathematician agent
- route non-trivial implementation changes through the Code Reviewer agent
- if blocked, add the blocker and mitigation strategy to `plan.md` instead of
  relying on tribal knowledge
