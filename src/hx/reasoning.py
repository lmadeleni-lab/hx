"""Stateful reasoning engine — reasoning gate, state transitions, and percolation monitor.

This module implements the bridge between hx governance and a stateful
decision engine where the LLM is a consultant, not the system itself.

Architecture: state -> reasoning (gate) -> simulation -> decision
-> execution -> feedback -> updated state
"""
from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any

from hx.audit import now_iso
from hx.config import STATE_DIR, ensure_hx_dirs
from hx.hexmap import HexMapError, load_hexmap
from hx.metrics import (
    HEX_PERCOLATION_THRESHOLD,
    _port_edge_weight,
    boundary_pressure,
    load_port_history,
    occupation_fraction,
    port_risk_snapshot,
)


class ReasoningMode(Enum):
    """Decision output from the reasoning gate."""
    LOCAL = "local"           # deterministic rules suffice
    LLM_SCOPED = "llm_scoped"  # LLM needed, but only for hot edges
    LLM_FULL = "llm_full"    # full LLM consultation required
    ESCALATE = "escalate"     # human intervention needed


# Thresholds for the reasoning gate
PRESSURE_LOCAL_MAX = 0.5       # below this: local reasoning OK
PRESSURE_LLM_SCOPED_MAX = 1.5  # below this: scoped LLM; above: full
RISK_LOCAL_MAX = 0.3           # max per-port risk for local mode
RISK_ESCALATE_MIN = 0.65       # above this: escalate to human
OCCUPATION_WARNING = 0.4       # approaching percolation


def reasoning_gate(
    root: Path,
    active_cell_id: str,
    radius: int,
) -> dict[str, Any]:
    """Decide whether to use local reasoning, scoped LLM, full LLM, or escalate.

    Reads existing metrics (boundary pressure, occupation fraction,
    port risk scores) and returns a decision with justification.
    This is the core of the stateful reasoning engine: the system
    decides WHEN to call the expensive LLM consultant.

    Returns:
        mode: ReasoningMode value
        signals: dict of metric values that informed the decision
        hot_edges: list of high-cost edges (for LLM_SCOPED mode)
        justification: human-readable explanation
    """
    try:
        hexmap = load_hexmap(root)
    except HexMapError:
        return {
            "mode": ReasoningMode.LLM_FULL.value,
            "signals": {},
            "hot_edges": [],
            "justification": "No hexmap — cannot assess locally.",
        }

    from hx.authz import allowed_cells as calc_allowed_cells
    allowed = calc_allowed_cells(hexmap, active_cell_id, radius)

    # Signal 1: Occupation fraction (percolation)
    occ = occupation_fraction(hexmap)

    # Signal 2: Boundary pressure (isoperimetrically normalized)
    task_proxy = {
        "radius": radius,
        "port_check": {
            "allowed_cells": allowed,
            "touched_cells": allowed,
        },
    }
    pressure = boundary_pressure(root, task_proxy)

    # Signal 3: Max port risk in the active scope
    history = load_port_history(root)
    max_risk = 0.0
    hot_edges: list[dict[str, Any]] = []
    for cell_id in allowed:
        cell = hexmap.cell(cell_id)
        for i, neighbor in enumerate(cell.neighbors):
            if neighbor is None:
                continue
            port = cell.ports[i] if i < len(cell.ports) else None
            if port is None:
                continue
            snapshot = port_risk_snapshot(
                history.get(port.port_id, {}),
            )
            risk = snapshot.get("policy_risk_score", 0.0)
            if risk > max_risk:
                max_risk = risk
            # Track edges with above-average cost
            from hx.ports import _find_port_between
            nbr_port = _find_port_between(hexmap, neighbor, cell_id)
            nbr_id = nbr_port.port_id if nbr_port else None
            weight = _port_edge_weight(history, port.port_id, nbr_id)
            if weight > 2.0 or risk > RISK_LOCAL_MAX:
                hot_edges.append({
                    "from": cell_id,
                    "to": neighbor,
                    "port_id": port.port_id,
                    "risk": risk,
                    "weight": weight,
                })

    signals = {
        "occupation_fraction": occ,
        "boundary_pressure": pressure,
        "max_port_risk": max_risk,
        "hot_edge_count": len(hot_edges),
        "percolation_warning": occ > OCCUPATION_WARNING,
        "percolation_critical": occ > HEX_PERCOLATION_THRESHOLD,
    }

    # Decision logic
    if max_risk >= RISK_ESCALATE_MIN:
        mode = ReasoningMode.ESCALATE
        justification = (
            f"Port risk {max_risk:.3f} exceeds escalation "
            f"threshold {RISK_ESCALATE_MIN}."
        )
    elif occ > HEX_PERCOLATION_THRESHOLD:
        mode = ReasoningMode.LLM_FULL
        justification = (
            f"Occupation {occ:.4f} exceeds percolation threshold "
            f"{HEX_PERCOLATION_THRESHOLD} — changes may propagate "
            f"unboundedly."
        )
    elif pressure > PRESSURE_LLM_SCOPED_MAX:
        mode = ReasoningMode.LLM_FULL
        justification = (
            f"Boundary pressure {pressure:.3f} is high — "
            f"full context needed."
        )
    elif pressure > PRESSURE_LOCAL_MAX or hot_edges:
        mode = ReasoningMode.LLM_SCOPED
        justification = (
            f"Pressure {pressure:.3f} or {len(hot_edges)} hot "
            f"edge(s) — scoped LLM consultation on hot boundaries."
        )
    else:
        mode = ReasoningMode.LOCAL
        justification = (
            f"All signals below thresholds (pressure={pressure:.3f}, "
            f"risk={max_risk:.3f}, occ={occ:.4f}) — local "
            f"deterministic reasoning suffices."
        )

    # Sort hot edges by risk descending for scoped prompts
    hot_edges.sort(key=lambda e: e["risk"], reverse=True)

    return {
        "mode": mode.value,
        "signals": signals,
        "hot_edges": hot_edges[:10],
        "justification": justification,
    }


def transition_state(
    root: Path,
    action: dict[str, Any],
    outcome: dict[str, Any],
) -> dict[str, Any]:
    """Apply a state transition and return the delta.

    Takes an action (tool call or decision) and its outcome,
    computes what changed in the system state, and persists
    the transition for audit and rollback.

    This replaces full recomputation with incremental updates.
    """
    ensure_hx_dirs(root)
    transition_log = root / STATE_DIR / "transitions.jsonl"

    # Compute the transition delta
    delta: dict[str, Any] = {
        "timestamp": now_iso(),
        "action_type": action.get("type", "unknown"),
        "action_tool": action.get("tool"),
        "outcome_status": outcome.get("status", "unknown"),
        "cells_affected": outcome.get("cells_affected", []),
        "ports_affected": outcome.get("ports_affected", []),
        "metrics_before": {},
        "metrics_after": {},
    }

    # Capture before-state for affected ports
    history = load_port_history(root)
    for port_id in outcome.get("ports_affected", []):
        entry = history.get(port_id, {})
        delta["metrics_before"][port_id] = port_risk_snapshot(entry)

    # Apply the outcome (the caller has already executed the action)
    # Re-snapshot after-state
    history = load_port_history(root)
    for port_id in outcome.get("ports_affected", []):
        entry = history.get(port_id, {})
        delta["metrics_after"][port_id] = port_risk_snapshot(entry)

    # Compute drift: did risk increase or decrease?
    risk_deltas: list[float] = []
    for port_id in outcome.get("ports_affected", []):
        before = delta["metrics_before"].get(port_id, {})
        after = delta["metrics_after"].get(port_id, {})
        before_risk = before.get("policy_risk_score", 0.0)
        after_risk = after.get("policy_risk_score", 0.0)
        risk_deltas.append(after_risk - before_risk)

    delta["risk_drift"] = round(sum(risk_deltas), 4) if risk_deltas else 0.0
    delta["risk_direction"] = (
        "increased" if delta["risk_drift"] > 0.01
        else "decreased" if delta["risk_drift"] < -0.01
        else "stable"
    )

    # Persist transition (append-only log)
    with open(transition_log, "a") as f:
        f.write(json.dumps(delta, default=str) + "\n")

    return delta


def check_feedback_integrity(
    root: Path,
    affected_ports: list[str],
) -> list[str]:
    """Run holonomy check on the subgraph affected by recent execution.

    After each execution cycle, verify that the affected ports
    haven't accumulated inconsistencies around their triangles.
    Returns warning strings (empty = consistent).
    """
    try:
        hexmap = load_hexmap(root)
    except HexMapError:
        return []

    from hx.ports import find_triangles, holonomy_check

    # Find which cells are affected
    affected_cells: set[str] = set()
    for cell in hexmap.cells:
        for port in cell.ports:
            if port is not None and port.port_id in affected_ports:
                affected_cells.add(cell.cell_id)

    if not affected_cells:
        return []

    # Find triangles that include affected cells
    all_triangles = find_triangles(hexmap)
    relevant_triangles = [
        tri for tri in all_triangles
        if any(c in affected_cells for c in tri)
    ]

    warnings: list[str] = []
    for triangle in relevant_triangles:
        warnings.extend(holonomy_check(hexmap, triangle))

    return warnings


def percolation_status(root: Path) -> dict[str, Any]:
    """Real-time percolation monitoring at cell and parent level.

    Returns current occupation fractions and phase status.
    """
    try:
        hexmap = load_hexmap(root)
    except HexMapError:
        return {"available": False}

    from hx.parents import (
        get_parent_groups,
        parent_boundary_occupation,
        parent_occupation_fraction,
    )

    global_occ = occupation_fraction(hexmap)
    threshold = HEX_PERCOLATION_THRESHOLD

    parent_status: list[dict[str, Any]] = []
    for group in get_parent_groups(hexmap):
        occ = parent_occupation_fraction(hexmap, group)
        bdry_occ = parent_boundary_occupation(hexmap, group)
        parent_status.append({
            "parent_id": group.parent_id,
            "occupation": occ,
            "boundary_occupation": bdry_occ,
            "phase": (
                "supercritical" if bdry_occ > threshold
                else "critical" if bdry_occ > OCCUPATION_WARNING
                else "subcritical"
            ),
        })

    return {
        "available": True,
        "global_occupation": global_occ,
        "threshold": threshold,
        "global_phase": (
            "supercritical" if global_occ > threshold
            else "critical" if global_occ > OCCUPATION_WARNING
            else "subcritical"
        ),
        "parent_groups": parent_status,
        "recommendation": (
            "Reduce port density or split cells"
            if global_occ > threshold
            else "Approaching threshold — monitor closely"
            if global_occ > OCCUPATION_WARNING
            else "Healthy — local reasoning viable"
        ),
    }


def build_scoped_prompt(
    root: Path,
    active_cell_id: str,
    radius: int,
    hot_edges: list[dict[str, Any]],
    task_description: str,
) -> str:
    """Build a focused prompt containing only high-cost edges.

    Used when reasoning_gate returns LLM_SCOPED — the LLM sees
    only where uncertainty is highest, saving tokens.
    """
    try:
        hexmap = load_hexmap(root)
    except HexMapError:
        return task_description

    cell = hexmap.cell(active_cell_id)
    from hx.authz import allowed_cells as calc_allowed_cells
    allowed = calc_allowed_cells(hexmap, active_cell_id, radius)

    # Include only cells involved in hot edges
    hot_cells: set[str] = {active_cell_id}
    for edge in hot_edges:
        hot_cells.add(edge["from"])
        hot_cells.add(edge["to"])

    edge_lines = []
    for edge in hot_edges[:8]:
        edge_lines.append(
            f"  {edge['from']} -> {edge['to']} "
            f"(risk={edge['risk']:.3f}, weight={edge['weight']:.2f})"
        )
    edges_text = "\n".join(edge_lines) or "  (none)"

    from hx.memory import load_memory_context
    memory = load_memory_context(root)
    memory_section = f"\n## Memory\n{memory}\n" if memory else ""

    return f"""You are an AI agent in hx governance (SCOPED MODE).

## Focus Area
- Active cell: {active_cell_id} (R{radius})
- Summary: {cell.summary}
- Allowed: {', '.join(allowed)}
- Focus cells: {', '.join(sorted(hot_cells))}

## High-Risk Boundaries (reason for consultation)
{edges_text}

## Task
{task_description}

## Rules
- Only modify files in allowed cells.
- These boundaries have elevated risk — be precise.
- active_cell_id="{active_cell_id}", radius={radius}
{memory_section}"""
