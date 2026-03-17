from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from hx.models import Cell, HexMap, ParentGroup

SIDE_COUNT = 6


def get_parent_groups(hexmap: HexMap) -> list[ParentGroup]:
    return hexmap.parent_groups or derive_parent_groups(hexmap)


def parent_group_map(hexmap: HexMap) -> dict[str, ParentGroup]:
    return {group.parent_id: group for group in get_parent_groups(hexmap)}


def cell_parent_map(hexmap: HexMap) -> dict[str, tuple[ParentGroup, str]]:
    mapping: dict[str, tuple[ParentGroup, str]] = {}
    for group in get_parent_groups(hexmap):
        mapping[group.center_cell_id] = (group, "center")
        for index, child in enumerate(group.children):
            if child is not None:
                mapping[child] = (group, str(index))
    return mapping


def resolve_parent_group(hexmap: HexMap, cell_id: str) -> dict[str, Any] | None:
    group_info = cell_parent_map(hexmap).get(cell_id)
    if group_info is None:
        return None
    group, slot = group_info
    return {
        "parent_id": group.parent_id,
        "center_cell_id": group.center_cell_id,
        "slot": slot,
    }


def _existing_group_by_center(existing: list[ParentGroup] | None) -> dict[str, ParentGroup]:
    return {
        group.center_cell_id: group
        for group in (existing or [])
    }


def _default_parent_summary(center: Cell) -> str:
    return f"Parent group centered on {center.cell_id}"


def _reachable_neighbors(hexmap: HexMap, center_cell_id: str) -> set[str]:
    return {
        neighbor
        for neighbor in hexmap.cell(center_cell_id).neighbors
        if neighbor is not None
    }


def derive_parent_groups(
    hexmap: HexMap,
    existing: list[ParentGroup] | None = None,
) -> list[ParentGroup]:
    existing_by_center = _existing_group_by_center(existing)
    assigned: set[str] = set()
    groups: list[ParentGroup] = []
    all_cell_ids = [
        cell.cell_id
        for cell in sorted(
            hexmap.cells,
            key=lambda cell: (
                -sum(1 for port in cell.ports if port is not None),
                -sum(1 for neighbor in cell.neighbors if neighbor is not None),
                cell.cell_id,
            ),
        )
    ]

    for center_id in all_cell_ids:
        if center_id in assigned:
            continue
        center = hexmap.cell(center_id)
        existing_group = existing_by_center.get(center_id)
        children: list[str | None] = [None] * SIDE_COUNT
        overrides = existing_group.overrides if existing_group is not None else {}
        override_children = (overrides or {}).get(
            "children",
            [None] * SIDE_COUNT,
        )
        override_children = (override_children + [None] * SIDE_COUNT)[:SIDE_COUNT]
        reachable = _reachable_neighbors(hexmap, center_id)

        for index, child_id in enumerate(override_children):
            if child_id is None:
                continue
            if child_id in assigned or child_id == center_id:
                continue
            if child_id not in {cell.cell_id for cell in hexmap.cells}:
                continue
            justification = (overrides or {}).get("justification")
            if child_id not in reachable and not justification:
                continue
            children[index] = child_id

        for index, neighbor in enumerate(center.neighbors):
            if children[index] is not None:
                continue
            if neighbor is None or neighbor in assigned or neighbor == center_id:
                continue
            children[index] = neighbor

        group = ParentGroup(
            parent_id=(
                existing_group.parent_id if existing_group is not None else f"parent_{center_id}"
            ),
            summary=(
                existing_group.summary
                if existing_group is not None and existing_group.summary
                else _default_parent_summary(center)
            ),
            center_cell_id=center_id,
            children=children,
            overrides=overrides,
            invariants=existing_group.invariants if existing_group is not None else [],
        )
        assigned.add(center_id)
        assigned.update(child for child in children if child is not None)
        groups.append(group)

    group_by_cell = {
        member: group.parent_id
        for group in groups
        for member in group.member_cells()
    }
    for group in groups:
        group.derived_neighbors = derive_parent_neighbors(hexmap, group, group_by_cell)
    return groups


def derive_parent_neighbors(
    hexmap: HexMap,
    group: ParentGroup,
    group_by_cell: dict[str, str] | None = None,
) -> list[str | None]:
    if group_by_cell is None:
        group_by_cell = {
            member: parent.parent_id
            for parent in get_parent_groups(hexmap)
            for member in parent.member_cells()
        }

    parent_neighbors: list[str | None] = [None] * SIDE_COUNT
    member_set = set(group.member_cells())
    center = hexmap.cell(group.center_cell_id)
    for index in range(SIDE_COUNT):
        candidates: Counter[str] = Counter()
        cell_ids = [group.center_cell_id]
        if group.children[index] is not None:
            cell_ids.append(group.children[index])
        for cell_id in cell_ids:
            cell = hexmap.cell(cell_id)
            for neighbor in cell.neighbors:
                if neighbor is None or neighbor in member_set:
                    continue
                parent_id = group_by_cell.get(neighbor)
                if parent_id and parent_id != group.parent_id:
                    candidates[parent_id] += 1
        if center.neighbors[index] is not None:
            parent_id = group_by_cell.get(center.neighbors[index])
            if parent_id and parent_id != group.parent_id:
                candidates[parent_id] += 2
        if candidates:
            parent_neighbors[index] = sorted(
                candidates.items(),
                key=lambda item: (-item[1], item[0]),
            )[0][0]
    return parent_neighbors


def _parent_group_connected(hexmap: HexMap, group: ParentGroup) -> bool:
    """Check that the subgraph induced by group members is connected."""
    members = group.member_cells()
    if len(members) <= 1:
        return True
    member_set = set(members)
    visited: set[str] = set()
    queue = [members[0]]
    visited.add(members[0])
    while queue:
        current = queue.pop()
        cell = hexmap.cell(current)
        for neighbor in cell.neighbors:
            if neighbor in member_set and neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)
    return visited == member_set


def parent_occupation_fraction(
    hexmap: HexMap, group: ParentGroup,
) -> float:
    """Fraction of port slots occupied by non-None ports in the group."""
    total = 0
    occupied = 0
    for cell_id in group.member_cells():
        cell = hexmap.cell(cell_id)
        for port in cell.ports:
            total += 1
            if port is not None:
                occupied += 1
    if total == 0:
        return 0.0
    return round(occupied / total, 4)


def validate_parent_groups(hexmap: HexMap) -> list[str]:
    groups = get_parent_groups(hexmap)
    errors: list[str] = []
    cell_ids = {cell.cell_id for cell in hexmap.cells}
    seen_parents: set[str] = set()
    assigned_children: dict[str, str] = {}
    for group in groups:
        if group.parent_id in seen_parents:
            errors.append(f"{group.parent_id}: duplicate parent_id")
        seen_parents.add(group.parent_id)
        if group.center_cell_id not in cell_ids:
            errors.append(f"{group.parent_id}: unknown center cell {group.center_cell_id}")
        if len(group.children) != SIDE_COUNT:
            errors.append(f"{group.parent_id}: children must have length 6")
        if len(group.derived_neighbors) != SIDE_COUNT:
            errors.append(f"{group.parent_id}: derived_neighbors must have length 6")
        reachable = (
            _reachable_neighbors(hexmap, group.center_cell_id)
            if group.center_cell_id in cell_ids
            else set()
        )
        justification = (group.overrides or {}).get("justification")
        for child in group.children:
            if child is None:
                continue
            if child not in cell_ids:
                errors.append(f"{group.parent_id}: unknown child cell {child}")
                continue
            if child == group.center_cell_id:
                errors.append(f"{group.parent_id}: center cell cannot also appear in children")
            if child in assigned_children:
                errors.append(
                    f"{group.parent_id}: child {child} already assigned to "
                    f"{assigned_children[child]}"
                )
            assigned_children[child] = group.parent_id
            if child not in reachable and not justification:
                errors.append(
                    f"{group.parent_id}: child {child} is not radius-1 reachable from center "
                    f"{group.center_cell_id} without override justification"
                )

    # Connectedness check for each parent group
    for group in groups:
        if not _parent_group_connected(hexmap, group):
            errors.append(
                f"{group.parent_id}: member cells are not connected"
            )

    derived_by_id = {group.parent_id: derive_parent_neighbors(hexmap, group) for group in groups}
    for group in groups:
        if group.derived_neighbors != derived_by_id[group.parent_id]:
            errors.append(f"{group.parent_id}: derived_neighbors do not match induced parent graph")
    return errors


def parent_group_context(hexmap: HexMap, parent_id: str) -> dict[str, Any]:
    group = parent_group_map(hexmap)[parent_id]
    cells = []
    for cell_id in group.member_cells():
        cell = hexmap.cell(cell_id)
        cells.append(
            {
                "cell_id": cell.cell_id,
                "summary": cell.summary,
                "invariants": cell.invariants,
                "tests": cell.tests,
            }
        )
    return {
        "parent_id": group.parent_id,
        "center_cell_id": group.center_cell_id,
        "children": group.children,
        "cells": cells,
        "derived_neighbors": group.derived_neighbors,
    }


def parent_boundary_ports(hexmap: HexMap, parent_id: str) -> list[dict[str, Any]]:
    groups = parent_group_map(hexmap)
    group = groups[parent_id]
    cell_to_parent = {
        member: parent.parent_id
        for parent in groups.values()
        for member in parent.member_cells()
    }
    boundary: list[dict[str, Any]] = []
    for cell_id in group.member_cells():
        cell = hexmap.cell(cell_id)
        for index, port in enumerate(cell.ports):
            neighbor = cell.neighbors[index]
            if port is None or neighbor is None:
                continue
            neighbor_parent = cell_to_parent.get(neighbor)
            if neighbor_parent is None or neighbor_parent == parent_id:
                continue
            boundary.append(
                {
                    "port_id": port.port_id,
                    "cell_id": cell_id,
                    "side_index": index,
                    "neighbor_cell_id": neighbor,
                    "neighbor_parent_id": neighbor_parent,
                    "direction": port.direction,
                }
            )
    return boundary


def parent_rollup_metrics(root: Path, hexmap: HexMap, parent_id: str) -> dict[str, Any]:
    from hx.metrics import (
        _normalized_entropy,
        load_port_history,
        port_risk_snapshot,
    )

    history = load_port_history(root)
    boundary_ports = parent_boundary_ports(hexmap, parent_id)
    snapshots = [port_risk_snapshot(history.get(item["port_id"], {})) for item in boundary_ports]
    group = parent_group_map(hexmap)[parent_id]
    members = set(group.member_cells())
    internal_edges = 0
    external_edges = 0
    for cell_id in members:
        cell = hexmap.cell(cell_id)
        for neighbor in cell.neighbors:
            if neighbor is None:
                continue
            if neighbor in members:
                internal_edges += 1
            else:
                external_edges += 1
    total_edges = internal_edges + external_edges
    cohesion = round(internal_edges / total_edges, 4) if total_edges else 1.0

    # Pooled entropy: collect all category events across boundary ports
    all_category_events: list[list[str]] = []
    for item in boundary_ports:
        entry = history.get(item["port_id"], {})
        for change in entry.get("changes", []):
            cats = change.get("categories", [])
            if cats:
                all_category_events.append(cats)
    pooled_entropy = _normalized_entropy(all_category_events)

    occ_fraction = parent_occupation_fraction(hexmap, group)

    churn_total = round(
        sum(float(s.get("churn", 0.0)) for s in snapshots), 4,
    )
    return {
        "parent_boundary_pressure": round(float(len(boundary_ports)), 4),
        "parent_port_pressure": round(
            sum(float(s.get("pressure", 0.0)) for s in snapshots), 4,
        ),
        "parent_churn": churn_total,
        "parent_entropy": pooled_entropy,
        "parent_architecture_potential": round(
            min(
                (
                    (len(boundary_ports) * 0.3)
                    + (pooled_entropy * 0.2)
                    + (churn_total * 0.2)
                    + ((1.0 - cohesion) * 0.3)
                ),
                1.0,
            ),
            4,
        ),
        "parent_cohesion": cohesion,
        "parent_occupation_fraction": occ_fraction,
        "parent_summary_stability": 0.0,
        "metric_maturity": {
            "parent_boundary_pressure": "Heuristic",
            "parent_port_pressure": "Heuristic",
            "parent_churn": "Heuristic",
            "parent_entropy": "Pooled",
            "parent_architecture_potential": "Heuristic",
            "parent_cohesion": "Heuristic",
            "parent_occupation_fraction": "Exact",
            "parent_summary_stability": "Heuristic",
        },
    }


def parent_summary(root: Path, hexmap: HexMap, parent_id: str) -> dict[str, Any]:
    from hx.metrics import load_port_history, port_risk_snapshot

    group = parent_group_map(hexmap)[parent_id]
    metrics = parent_rollup_metrics(root, hexmap, parent_id)
    boundary_ports = parent_boundary_ports(hexmap, parent_id)
    risky_cells: Counter[str] = Counter()
    risky_port_ids = []
    history = load_port_history(root)
    for item in boundary_ports:
        snapshot = port_risk_snapshot(history.get(item["port_id"], {}))
        risky_port_ids.append({"port_id": item["port_id"], **snapshot})
        risky_cells[item["cell_id"]] += snapshot.get("pressure", 0.0)
    risky_port_ids = sorted(
        risky_port_ids,
        key=lambda item: item["policy_risk_score"],
        reverse=True,
    )[:5]
    child_summaries = []
    for cell_id in group.member_cells():
        cell = hexmap.cell(cell_id)
        child_summaries.append(
            {
                "cell_id": cell.cell_id,
                "summary": cell.summary,
                "invariants": cell.invariants,
                "tests": cell.tests,
            }
        )
    return {
        "parent_id": group.parent_id,
        "summary": group.summary,
        "center_cell_id": group.center_cell_id,
        "children": group.children,
        "derived_neighbors": group.derived_neighbors,
        "member_cells": group.member_cells(),
        "boundary_ports": boundary_ports,
        "metrics": metrics,
        "child_summaries": child_summaries,
        "risky_cells": [
            {"cell_id": cell_id, "pressure": pressure}
            for cell_id, pressure in risky_cells.most_common()
        ],
        "risky_ports": risky_port_ids,
    }


def parent_groups_overview(root: Path, hexmap: HexMap) -> list[dict[str, Any]]:
    return [
        {
            "parent_id": group.parent_id,
            "center_cell_id": group.center_cell_id,
            "children": group.children,
            "derived_neighbors": group.derived_neighbors,
            "summary": group.summary,
            "metrics": parent_rollup_metrics(root, hexmap, group.parent_id),
        }
        for group in get_parent_groups(hexmap)
    ]


def top_risky_parents(root: Path, hexmap: HexMap, n: int = 10) -> list[dict[str, Any]]:
    parents = parent_groups_overview(root, hexmap)
    return sorted(
        parents,
        key=lambda item: item["metrics"]["parent_architecture_potential"],
        reverse=True,
    )[:n]


def parent_report_markdown(root: Path, hexmap: HexMap, parent_id: str) -> str:
    summary = parent_summary(root, hexmap, parent_id)
    metrics = summary["metrics"]
    lines = ["# hx parent metrics report", ""]
    lines.append(f"- parent_id: `{parent_id}`")
    lines.append(f"- center_cell_id: `{summary['center_cell_id']}`")
    lines.append(f"- parent_boundary_pressure: {metrics['parent_boundary_pressure']}")
    lines.append(f"- parent_port_pressure: {metrics['parent_port_pressure']}")
    lines.append(f"- parent_churn: {metrics['parent_churn']}")
    lines.append(f"- parent_entropy: {metrics['parent_entropy']}")
    lines.append(f"- parent_architecture_potential: {metrics['parent_architecture_potential']}")
    lines.append(f"- parent_cohesion: {metrics['parent_cohesion']}")
    return "\n".join(lines) + "\n"
