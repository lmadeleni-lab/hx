# Hex Model

`hx` organizes a repository into hexagonal cells. Every task must name:

- `active_cell_id`
- `context_radius`

Radius defines which neighbor rings are authorized. `R0` means the active cell
only. `R1` adds direct neighbors. Every cell has six neighbor slots, which may
be `null`.

## Parent Hex Groups

`hx` now also supports a second, coarse-grained topology layer:
`parent_groups`.

A parent group contains:

- one `center_cell_id`
- six child slots aligned to the same hex side ordering as cells
- optional `null` child slots
- derived neighboring parent groups induced from child-level cross-group
  boundaries

Important boundary:

- cells remain the primary enforcement primitive
- parent groups do not replace cell/radius authorization in `0.1.x`
- parent groups are additive and are used for summarization, watch views,
  scheduler rollups, MCP context compression, and parent-level risk reporting

`HEXMAP.json` now supports a top-level `parent_groups` array. Each entry can
carry:

- `parent_id`
- `summary`
- `center_cell_id`
- `children[6]`
- `overrides`
- `invariants`
- `derived_neighbors[6]`

`hx hex build` derives parent groups automatically and preserves explicit
overrides when present. `hx hex validate` validates both the cell graph and the
parent-group graph.

## Enforcement

- reads, writes, tests, and commands are authorized against allowed cells
- radius expansion must be justified
- cross-cell changes are checked through ports instead of informal reach-through

## Terminal View

For local operator visibility, `hx` can render a cell and its six neighbor
slots directly in the terminal:

```bash
hx hex show <cell_id> --radius 1
```

The view currently includes:

- the active center cell
- all six side labels (`N`, `NE`, `SE`, `S`, `SW`, `NW`)
- the neighbor cell id or `null`
- a fulfillment status per side:
  `fulfilled`,
  `neighbor-only`,
  `stray-port`,
  `mismatch`,
  `asymmetric`,
  or `empty`
- the allowed cells currently in scope for the chosen radius

For richer terminal streaming during command execution, use:

```bash
hx --ui-mode expanded <command>
```

For a continuously redrawn operator dashboard, use:

```bash
hx --ui-mode expanded hex watch <cell_id> --radius 1
```

`hex watch` currently shows:

- the live hex neighborhood panel
- recent audit runs with status
- recent audit events from recorded runs
- parent context for the active cell when a parent group is available
- a tick/interval header for the redraw loop

## Parent Views

For the coarse-grained parent layer, `hx` exposes:

```bash
hx hex parent show <parent_id>
hx hex parent summarize <parent_id>
hx --ui-mode expanded hex parent watch <parent_id>
```

`hx hex parent show` renders:

- the parent center cell
- the six child slots
- the derived neighboring parent on each side

`hx hex parent summarize` emits structured JSON for:

- child summaries
- boundary ports
- risky child ports
- risky child cells
- heuristic parent metrics

`hx hex parent watch` extends the mini-TUI with:

- the parent neighborhood panel
- neighboring parents
- risky boundary ports
- recent boundary-relevant audit events
- a parent summary panel with pressure, cohesion, and parent potential

Useful flags:

- `--interval 0.5` to redraw more frequently
- `--iterations 10` to run a bounded watch session
