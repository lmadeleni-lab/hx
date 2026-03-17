"""Status dashboard: git-status-style governance overview."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from hx.audit import list_runs
from hx.authz import allowed_cells as calc_allowed_cells
from hx.hexmap import load_hexmap, resolve_cell_id
from hx.metrics import top_risky_ports
from hx.models import AuditRun
from hx.policy import default_radius, load_policy
from hx.ui import paint


def gather_status(root: Path) -> dict[str, Any]:
    """Gather all status data for the dashboard."""
    hexmap = load_hexmap(root)
    policy = load_policy(root)

    # Resolve active cell from CWD
    try:
        cwd_rel = str(Path.cwd().relative_to(root))
    except ValueError:
        cwd_rel = ""
    active_cell_id = resolve_cell_id(hexmap, cwd_rel) if cwd_rel else None
    if active_cell_id is None and hexmap.cells:
        active_cell_id = hexmap.cells[0].cell_id

    radius = default_radius(policy)
    allowed = calc_allowed_cells(hexmap, active_cell_id, radius) if active_cell_id else []
    cell = hexmap.cell(active_cell_id) if active_cell_id else None

    runs = list(reversed(list_runs(root)))
    risky = top_risky_ports(root, 5)

    open_runs = [r for r in runs[:20] if r.status == "running"]

    return {
        "active_cell_id": active_cell_id,
        "radius": radius,
        "allowed_cells": allowed,
        "summary": cell.summary if cell else "",
        "invariants": cell.invariants if cell else [],
        "recent_runs": runs[:5],
        "risky_ports": risky,
        "open_runs": open_runs,
        "total_cells": len(hexmap.cells),
    }


def render_status(root: Path, *, color: bool = False) -> str:
    """Render the status dashboard as a string."""
    data = gather_status(root)
    lines: list[str] = []

    # Header
    header = paint("hx status", "bold", "blue", color=color)
    lines.append(header)
    lines.append(paint("─" * 50, "dim", color=color))

    # Cell info
    cell_id = data["active_cell_id"] or "unknown"
    cell_label = paint(cell_id, "bold", "green", color=color)
    radius_label = paint(f"R{data['radius']}", "cyan", color=color)
    lines.append(f"Active cell:  {cell_label}  ({radius_label})")
    if data["summary"]:
        lines.append(f"Summary:      {data['summary']}")
    allowed = data["allowed_cells"]
    if allowed:
        lines.append(f"Allowed:      {', '.join(allowed)}")
    if data["invariants"]:
        for inv in data["invariants"]:
            lines.append(f"Invariant:    {inv}")
    lines.append(f"Total cells:  {data['total_cells']}")
    lines.append("")

    # Recent runs
    runs: list[AuditRun] = data["recent_runs"]
    if runs:
        lines.append(paint("Recent audit runs:", "bold", color=color))
        for run in runs:
            if run.status == "ok":
                glyph = paint("✓", "green", color=color)
            elif run.status == "running":
                glyph = paint("⋯", "yellow", color=color)
            else:
                glyph = paint("✗", "red", color=color)
            run_id_short = run.run_id[:8]
            lines.append(f"  {glyph} {run.command:<20} {run_id_short}  [{run.status}]")
    else:
        lines.append(paint("No audit runs yet.", "dim", color=color))
    lines.append("")

    # Risky ports
    risky = data["risky_ports"]
    if risky:
        lines.append(paint("Risky ports:", "bold", color=color))
        for item in risky:
            risk = item.get("policy_risk_score", 0)
            risk_color = "red" if risk > 0.5 else "yellow" if risk > 0.2 else "green"
            score = paint(f"risk={risk:.2f}", risk_color, color=color)
            lines.append(f"  {item['port_id']}  {score}")
    else:
        lines.append(paint("No risky ports.", "dim", color=color))
    lines.append("")

    # Open runs
    open_runs = data["open_runs"]
    if open_runs:
        lines.append(paint("Open obligations:", "bold", "yellow", color=color))
        for run in open_runs:
            lines.append(f"  ⋯ {run.command} ({run.run_id[:8]})")
    else:
        lines.append(paint("No open obligations.", "dim", color=color))

    return "\n".join(lines)
