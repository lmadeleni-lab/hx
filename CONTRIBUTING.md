# Contributing

1. Create a virtualenv and install `pip install -e .[dev]`.
2. Run `ruff check .` and `pytest`.
3. Keep changes scoped to the smallest viable cell and radius.
4. Update docs and tests with behavior changes.

For contract-affecting or metric-affecting changes:

- include migration notes and proof artifacts
- update `plan.md` if sequencing, risk, or metric meaning changed
- update `CHANGELOG.md` for user-visible behavior changes
- update docs when proof tiers, schema envelopes, benchmark reporting, or
  policy thresholds change

Before proposing a release-facing change, read:

- `docs/release.md`
- `docs/contracts.md`
- `docs/metrics.md`
