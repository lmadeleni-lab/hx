# Adoption Walkthrough

This walkthrough shows the intended "golden path" for a repository adopting
`hx`.

Install note:

- the currently supported install contract is a clean package install from a
  source checkout or built wheel
- the current supported host target is macOS terminal sessions
- editable installs are a contributor convenience, not the only supported path
- standard prerequisites are `python3`, `git`, and a macOS terminal shell
- interactive terminal use now includes colored status lines and a live
  thinking/loading indicator on `stderr`
- `--ui-mode expanded` enables richer streaming of task-level progress

## 1. Initialize the Repo

```bash
hx init
hx hex build
hx hex validate
```

This creates starter policy, hex map, agent guidance, and benchmark templates.

## 2. Refine the Hex Map

Review `HEXMAP.json` and make sure:

- each cell has a meaningful summary
- paths map to real architectural regions
- tests are listed for each cell
- neighbors and ports reflect real cross-cell boundaries

## 3. Run the MCP Server

```bash
hx mcp serve --transport stdio
```

To inspect the local topology before starting work:

```bash
hx hex show root --radius 1
```

For a live operator view while work is happening:

```bash
hx --ui-mode expanded hex watch root --radius 1
```

Then connect your agent CLI through MCP and prefer this order:

1. resolve the active cell
2. fetch allowed cells at the current radius
3. load scoped context
4. stage patches
5. run port and proof checks
6. commit only after verification

## 4. Perform a Scoped Change

Typical flow:

```text
repo.stage_patch -> port.check -> proof.collect -> proof.verify -> repo.commit_patch
```

For breaking or high-risk changes, expect:

- stricter proof obligations
- governance artifacts under `.hx/artifacts/<task_id>/`
- possible human approval before commit

If commit is denied, treat the denial reason as the next-action guide:

- re-stage if the patch changed after analysis
- complete missing proof collection or verification if obligations are unsatisfied
- obtain approval if the change is breaking or high-risk in the current mode
- expand radius only with explicit justification when the change is genuinely
  outside the active scope

## 5. Inspect Audit and Metrics

Use:

```bash
hx log
```

This gives a run summary plus the top risky ports by current policy-oriented
risk scoring.

## 6. Run a Benchmark

```bash
hx benchmark run battery.json
hx benchmark report
```

If you include audit run ids in the task battery, benchmark reports can also
summarize locality and proof-coverage variance from real `hx` runs.

## 7. Interpret Results Correctly

- proof, risk, and benchmark outputs are useful now
- some metrics are normalized, but most are still heuristic
- replay is best-effort and permission-preserving, not a guarantee that every
  historical command can be re-executed in every future environment
- benchmark output is descriptive unless future calibration work says otherwise

See `docs/metrics.md`, `docs/contracts.md`, and `docs/benchmarking.md` for the
governance details behind these outputs.
