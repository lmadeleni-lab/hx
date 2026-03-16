from __future__ import annotations

from pathlib import Path
from typing import Any

from hx.hexmap import load_hexmap
from hx.metrics import top_risky_ports
from hx.parents import resolve_parent_group, top_risky_parents


def recommend_hot_cells(
    root: Path,
    failing_tests: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    failing_tests = failing_tests or []
    risky = top_risky_ports(root, 10)
    hot = []
    for item in risky:
        hot.append(
            {
                "port_id": item["port_id"],
                "recommended_radius": 1 if item["policy_risk_score"] < 2 else 2,
                "guardianship": "strict" if item["policy_risk_score"] >= 2 else "normal",
            }
        )
    for failure in failing_tests:
        hot.append(
            {
                "cell_id": failure.get("cell_id"),
                "recommended_radius": 1,
                "guardianship": "normal",
            }
        )
    return hot


def recommend_hot_parents(
    root: Path,
    failing_tests: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    failing_tests = failing_tests or []
    hexmap = load_hexmap(root)
    hot = []
    for item in top_risky_parents(root, hexmap, 10):
        metrics = item["metrics"]
        hot.append(
            {
                "parent_id": item["parent_id"],
                "recommended_radius": 1 if metrics["parent_architecture_potential"] < 0.5 else 2,
                "guardianship": (
                    "strict" if metrics["parent_architecture_potential"] >= 0.5 else "normal"
                ),
            }
        )
    for failure in failing_tests:
        cell_id = failure.get("cell_id")
        if not cell_id:
            continue
        resolved = resolve_parent_group(hexmap, cell_id)
        if resolved is None:
            continue
        hot.append(
            {
                "parent_id": resolved["parent_id"],
                "hot_cell_id": cell_id,
                "recommended_radius": 1,
                "guardianship": "normal",
            }
        )
    return hot
