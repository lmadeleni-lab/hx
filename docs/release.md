# Release Policy

`hx` is currently pre-1.0 and uses conservative semantic versioning.

## Current Release Target

The current publishability target is `0.1.0`.

For `0.1.0`, the intended public contract is:

- CLI commands:
  `hx init`,
  `hx hex build`,
  `hx hex validate`,
  `hx mcp serve`,
  `hx doctor`,
  `hx log`,
  `hx replay`,
  `hx benchmark validate`,
  `hx benchmark run`,
  `hx benchmark report`
- MCP tools:
  `hex.resolve_cell`,
  `hex.allowed_cells`,
  `hex.context`,
  `hex.neighbors`,
  `hex.radius_expand_request`,
  `port.describe`,
  `port.surface`,
  `port.surface_diff`,
  `port.check`,
  `repo.read`,
  `repo.search`,
  `repo.stage_patch`,
  `repo.commit_patch`,
  `repo.approve_patch`,
  `repo.abort_patch`,
  `repo.diff`,
  `repo.files_touched`,
  `proof.collect`,
  `proof.verify`,
  `proof.attach`,
  `cmd.run`,
  `tests.run`,
  `metrics.compute`,
  `metrics.report`,
  `risk.top_ports`
- governance artifact schema:
  `hx.governance.v1`
- metric outputs:
  stable as named outputs, but still allowed to evolve semantically when
  explicitly labeled heuristic or policy-chosen

Current install contract proven by CI:

- macOS terminal-hosted package smoke coverage
- build the package
- install the resulting wheel into a fresh virtual environment
- run `hx --help`
- run `hx init`
- run `hx hex build`
- run `hx hex validate`

This is the current supported packaging claim. A public package index release is
not yet part of the release contract.

Current host target for `0.1.0`:

- macOS terminal sessions only
- interactive terminal UX includes a startup screen plus colored status/loading
  feedback on `stderr`

## Versioning

- `0.x.y` means the project is still evolving and may change quickly
- patch releases (`0.x.y -> 0.x.z`) are for fixes, doc-only corrections, and
  compatibility-preserving maintenance
- minor releases (`0.x.y -> 0.(x+1).0`) are for new features, new tools,
  broadened docs, or behavior changes that remain aligned with the current
  thesis
- any change that breaks a published CLI contract, MCP tool shape, artifact
  schema, or documented policy expectation must be called out explicitly in
  release notes even before `1.0`

## Release Notes

Each release note should include:

- summary of user-visible changes
- new commands, tools, or docs
- enforcement changes
- metric meaning changes
- changes to heuristic vs normalized metric maturity
- migration steps if any schema, contract, or policy interpretation changed

If a release changes any public contract surface, the release notes must state
whether the change affects:

- enforcement behavior
- public interpretation or reporting semantics
- both

## Compatibility Expectations

Call out these items explicitly whenever they change:

- MCP tool names or parameter shapes
- governance artifact schemas
- benchmark report semantics
- metric formulas or maturity labels
- policy defaults

The following compatibility promises apply for `0.1.0`:

- CLI command names listed in this document are intended public names
- MCP tool names listed in this document are intended public names
- `hx.governance.v1` is the first intended public governance artifact schema
- additive artifact fields are acceptable within `hx.governance.v1`
- metric values may change when heuristic formulas are improved, but those
  semantic changes must be called out in release notes and migration notes
- benchmark reports remain descriptive and must not be documented as
  inferential

## Before Tagging a Release

1. Run `ruff check .`.
2. Run `pytest`.
3. Verify README, benchmark guidance, integration docs, and release docs still
   match current behavior.
4. Update `CHANGELOG.md`.
5. Add release notes that separate:
   safe maintenance changes,
   enforcement changes,
   schema or migration-sensitive changes.
6. Rehearse a clean package install from a built artifact in a fresh virtual
   environment.
