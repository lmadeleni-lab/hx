from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hx.audit import list_runs
from hx.config import STATE_DIR
from hx.hexmap import HexMapError, load_hexmap

PORT_HISTORY = "port_history.json"
CHANGE_CATEGORY_COUNT = 6
CHURN_HALF_LIFE_DAYS = 30.0
CHURN_DECAY_LAMBDA = math.log(2) / CHURN_HALF_LIFE_DAYS

# Hex lattice percolation threshold (exact for site percolation)
HEX_PERCOLATION_THRESHOLD = 0.5

ARCHITECTURE_POTENTIAL_WEIGHTS = {
    "boundary_pressure": 0.25,
    "port_entropy": 0.15,
    "port_churn": 0.1,
    "propagation_depth": 0.15,
    "approval_rate": 0.1,
    "proof_burden": 0.1,
    "entropy_churn_interaction": 0.15,
}
ARCHITECTURE_POTENTIAL_SCALES = {
    "boundary_pressure": 6.0,
    "port_churn": 3.0,
    "proof_burden": 4.0,
}

# Normalization scales for policy_risk_score components
RISK_NORMALIZATION_SCALES = {
    "churn": 5.0,
    "pressure": 20.0,
    "failures": 5.0,
}


def _history_path(root: Path) -> Path:
    path = root / STATE_DIR / PORT_HISTORY
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("{}\n")
    return path


def load_port_history(root: Path) -> dict[str, Any]:
    return json.loads(_history_path(root).read_text())


def save_port_history(root: Path, data: dict[str, Any]) -> None:
    _history_path(root).write_text(json.dumps(data, indent=2) + "\n")


def hex_isoperimetric_bound(n: int) -> float:
    """Minimum boundary size for n cells in a hex lattice.

    For the optimal (compact) arrangement, boundary ~ 6*sqrt(n/3).
    """
    if n <= 0:
        return 0.0
    if n == 1:
        return 6.0
    r = math.sqrt(n / 3.0)
    return round(6.0 * r, 3)


def occupation_fraction(hexmap: Any) -> float:
    """Fraction of port slots occupied by non-None ports across all cells."""
    total_slots = 0
    occupied = 0
    for cell in hexmap.cells:
        for port in cell.ports:
            total_slots += 1
            if port is not None:
                occupied += 1
    if total_slots == 0:
        return 0.0
    return round(occupied / total_slots, 4)


def _port_edge_weight(
    port_history: dict[str, Any], port_id: str | None,
) -> float:
    """Compute information-weighted edge cost for a boundary port.

    Combines port entropy and churn into a single weight.
    Falls back to 1.0 for ports without history.
    """
    if port_id is None:
        return 1.0
    entry = port_history.get(port_id)
    if entry is None:
        return 1.0
    changes = entry.get("changes", [])
    if not changes:
        return 1.0
    category_events = [c.get("categories", []) for c in changes]
    entropy = _normalized_entropy(category_events)
    churn = _decayed_churn(changes)
    churn_norm = min(churn / 5.0, 1.0)
    # Weight: base 1.0 + entropy contribution + churn contribution
    return round(1.0 + entropy + churn_norm, 4)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def record_port_change(
    root: Path,
    task_id: str,
    impacts: list[dict[str, Any]],
    success: bool,
) -> None:
    history = load_port_history(root)
    recorded_at = _now_iso()
    for impact in impacts:
        port_id = impact["port_id"]
        entry = history.setdefault(port_id, {"changes": [], "failures": 0, "touches": 0})
        entry["touches"] += 1
        if not success:
            entry["failures"] += 1
        entry["changes"].append(
            {
                "task_id": task_id,
                "categories": impact.get("categories", []),
                "recorded_at": recorded_at,
            }
        )
    save_port_history(root, history)


def _shannon_entropy(category_events: list[list[str]]) -> float:
    counter: Counter[str] = Counter()
    total = 0
    for categories in category_events:
        for category in categories:
            counter[category] += 1
            total += 1
    if total == 0:
        return 0.0
    entropy = 0.0
    for count in counter.values():
        p = count / total
        entropy -= p * math.log2(p)
    return round(entropy, 4)


def _normalized_entropy(category_events: list[list[str]]) -> float:
    raw_entropy = _shannon_entropy(category_events)
    if raw_entropy == 0.0:
        return 0.0
    return round(raw_entropy / math.log2(CHANGE_CATEGORY_COUNT), 4)


def _decayed_churn(
    changes: list[dict[str, Any]],
    *,
    reference_time: datetime | None = None,
) -> float:
    if not changes:
        return 0.0
    reference = reference_time or datetime.now(UTC)
    total = 0.0
    for change in changes:
        recorded_at = change.get("recorded_at")
        if not recorded_at:
            total += 1.0
            continue
        try:
            change_time = datetime.fromisoformat(recorded_at)
        except ValueError:
            total += 1.0
            continue
        if change_time.tzinfo is None:
            change_time = change_time.replace(tzinfo=UTC)
        age_days = max((reference - change_time).total_seconds() / 86400.0, 0.0)
        total += math.exp(-CHURN_DECAY_LAMBDA * age_days)
    return round(total, 4)


def _boundary_pressure_heuristic(task: dict[str, Any]) -> float:
    touched_cells = task.get("port_check", {}).get("touched_cells", [])
    cross_cell = max(len(set(touched_cells)) - 1, 0)
    expansions = max((task.get("radius") or 0), 0)
    imports = task.get("port_check", {}).get("cross_cell_imports", 0)
    return round((cross_cell * 1.5) + expansions + (imports * 0.25), 3)


def boundary_pressure(root: Path, task: dict[str, Any]) -> float:
    """Information-weighted boundary pressure normalized against hex isoperimetric bound."""
    try:
        hexmap = load_hexmap(root)
    except HexMapError:
        return _boundary_pressure_heuristic(task)

    port_check = task.get("port_check", {})
    active_cells = port_check.get("allowed_cells") or port_check.get("touched_cells", [])
    active_set = set(active_cells)
    if not active_set:
        return _boundary_pressure_heuristic(task)

    known_cell_ids = {cell.cell_id for cell in hexmap.cells}
    known_active_cells = [cell_id for cell_id in active_set if cell_id in known_cell_ids]
    if not known_active_cells:
        return _boundary_pressure_heuristic(task)

    # Load port history for information-weighted edges
    history = load_port_history(root)

    cut_weight = 0.0
    for cell_id in known_active_cells:
        cell = hexmap.cell(cell_id)
        for i, neighbor in enumerate(cell.neighbors):
            if neighbor is not None and neighbor not in active_set:
                port = cell.ports[i] if i < len(cell.ports) else None
                port_id = port.port_id if port else None
                cut_weight += _port_edge_weight(history, port_id)
    return round(cut_weight, 3)


def _weighted_proof_coverage(task: dict[str, Any]) -> tuple[float, float]:
    obligations = task.get("port_check", {}).get("obligations", {})
    check_specs = obligations.get("check_specs", [])
    artifact_specs = obligations.get("artifact_specs", [])
    proofs = task.get("proofs", {})
    proof_checks = proofs.get("checks", [])
    proof_artifacts = set(proofs.get("artifacts", []))

    if not check_specs and not artifact_specs:
        required_checks = obligations.get("required_checks", [])
        if not required_checks:
            return 1.0, 1.0
        satisfied_checks = sum(1 for check in proof_checks if check.get("returncode", 1) == 0)
        raw = round(satisfied_checks / len(required_checks), 3)
        return raw, raw

    successful_commands = {
        check.get("command")
        for check in proof_checks
        if check.get("returncode", 1) == 0 and check.get("command")
    }
    total_weight = 0.0
    satisfied_weight = 0.0
    total_items = 0
    satisfied_items = 0

    for spec in check_specs:
        total_items += 1
        total_weight += float(spec.get("weight", 1.0))
        if spec["value"] in successful_commands:
            satisfied_items += 1
            satisfied_weight += float(spec.get("weight", 1.0))

    for spec in artifact_specs:
        total_items += 1
        total_weight += float(spec.get("weight", 1.0))
        if spec["value"] in proof_artifacts:
            satisfied_items += 1
            satisfied_weight += float(spec.get("weight", 1.0))

    if total_items == 0 or total_weight == 0:
        return 1.0, 1.0

    return round(satisfied_weight / total_weight, 3), round(satisfied_items / total_items, 3)


def _bounded_ratio(value: float, scale: float) -> float:
    if scale <= 0:
        return 0.0
    return round(min(max(value, 0.0) / scale, 1.0), 4)


def _proof_burden(task: dict[str, Any]) -> float:
    obligations = task.get("port_check", {}).get("obligations", {})
    check_specs = obligations.get("check_specs", [])
    artifact_specs = obligations.get("artifact_specs", [])
    if check_specs or artifact_specs:
        return round(
            sum(float(spec.get("weight", 1.0)) for spec in check_specs)
            + sum(float(spec.get("weight", 1.0)) for spec in artifact_specs),
            4,
        )
    return float(
        len(obligations.get("required_checks", []))
        + len(obligations.get("required_artifacts", []))
    )


def _task_architecture_potential(
    task: dict[str, Any],
    metrics: dict[str, Any],
) -> tuple[float, dict[str, float]]:
    proof_burden = _proof_burden(task)
    radius = float(task.get("radius", 0) or 0)
    entropy_val = round(float(metrics.get("port_entropy", 0.0)), 4)
    churn_val = _bounded_ratio(
        float(metrics.get("port_churn", 0.0)),
        ARCHITECTURE_POTENTIAL_SCALES["port_churn"],
    )
    components = {
        "boundary_pressure": _bounded_ratio(
            float(metrics.get("boundary_pressure", 0.0)),
            ARCHITECTURE_POTENTIAL_SCALES["boundary_pressure"],
        ),
        "port_entropy": entropy_val,
        "port_churn": churn_val,
        "propagation_depth": round(radius / (1.0 + radius), 4),
        "approval_rate": (
            1.0 if task.get("port_check", {}).get("requires_approval")
            else 0.0
        ),
        "proof_burden": _bounded_ratio(
            proof_burden,
            ARCHITECTURE_POTENTIAL_SCALES["proof_burden"],
        ),
        # Nonlinear interaction: compounding risk
        "entropy_churn_interaction": round(entropy_val * churn_val, 4),
    }
    potential = round(
        sum(
            ARCHITECTURE_POTENTIAL_WEIGHTS[name] * value
            for name, value in components.items()
        ),
        4,
    )
    return potential, components


def compute_metrics(root: Path, task: dict[str, Any]) -> dict[str, Any]:
    history = load_port_history(root)
    impacted = task.get("port_check", {}).get("impacted_ports", [])
    entropies = []
    raw_entropies = []
    churn = []
    raw_churn = []
    failures = []
    for impact in impacted:
        entry = history.get(impact["port_id"], {"changes": [], "failures": 0, "touches": 0})
        changes = entry.get("changes", [])
        category_events = [change["categories"] for change in entry["changes"]]
        raw_entropies.append(_shannon_entropy(category_events))
        entropies.append(_normalized_entropy(category_events))
        churn.append(_decayed_churn(changes))
        raw_churn.append(len(changes))
        failures.append(entry.get("failures", 0))
    locality_cells = task.get("port_check", {}).get("touched_cells", [])
    proof_coverage, proof_coverage_raw = _weighted_proof_coverage(task)
    metrics = {
        "locality": round(1.0 / (1 + max(len(set(locality_cells)) - 1, 0)), 3),
        "radius_used": task.get("radius", 0),
        "boundary_pressure": boundary_pressure(root, task),
        "boundary_pressure_heuristic": _boundary_pressure_heuristic(task),
        "port_entropy": round(sum(entropies) / len(entropies), 4) if entropies else 0.0,
        "port_entropy_raw": (
            round(sum(raw_entropies) / len(raw_entropies), 4) if raw_entropies else 0.0
        ),
        "port_churn": round(sum(churn) / len(churn), 3) if churn else 0.0,
        "port_churn_raw": round(sum(raw_churn) / len(raw_churn), 3) if raw_churn else 0.0,
        "propagation_depth": task.get("radius", 0),
        "proof_coverage": proof_coverage,
        "proof_coverage_raw": proof_coverage_raw,
        "recent_failures": sum(failures),
    }
    architecture_potential, architecture_components = _task_architecture_potential(task, metrics)
    metrics["architecture_potential"] = architecture_potential
    metrics["architecture_potential_components"] = architecture_components
    return metrics


DEFAULT_RISK_WEIGHTS = {"entropy": 0.35, "churn": 0.25, "pressure": 0.25, "failures": 0.15}


def policy_risk_score(
    port_entry: dict[str, Any],
    *,
    entropy: float,
    churn: float,
    pressure: float,
    weights: dict[str, float] | None = None,
) -> float:
    """Normalized risk score in [0,1] with nonlinear interaction term.

    All components are normalized to [0,1] before combining.
    Includes an entropy*churn interaction term for compounding risk.
    """
    w = weights or DEFAULT_RISK_WEIGHTS
    failures = port_entry.get("failures", 0)

    # Normalize unbounded components to [0,1]
    churn_norm = _bounded_ratio(churn, RISK_NORMALIZATION_SCALES["churn"])
    pressure_norm = _bounded_ratio(
        pressure, RISK_NORMALIZATION_SCALES["pressure"],
    )
    failures_norm = _bounded_ratio(
        failures, RISK_NORMALIZATION_SCALES["failures"],
    )

    # Linear terms
    linear = (
        (entropy * w.get("entropy", 0.35))
        + (churn_norm * w.get("churn", 0.25))
        + (pressure_norm * w.get("pressure", 0.25))
        + (failures_norm * w.get("failures", 0.15))
    )

    # Nonlinear interaction: entropy * churn compound risk
    interaction = entropy * churn_norm * 0.15

    return round(min(linear + interaction, 1.0), 4)


def port_risk_snapshot(port_entry: dict[str, Any]) -> dict[str, Any]:
    changes = port_entry.get("changes", [])
    category_events = [change.get("categories", []) for change in changes]
    entropy_raw = _shannon_entropy(category_events)
    entropy = _normalized_entropy(category_events)
    churn = _decayed_churn(changes)
    churn_raw = len(changes)
    pressure = port_entry.get("touches", 0)
    return {
        "entropy": entropy,
        "entropy_raw": entropy_raw,
        "churn": churn,
        "churn_raw": churn_raw,
        "pressure": pressure,
        "recent_failures": port_entry.get("failures", 0),
        "policy_risk_score": policy_risk_score(
            port_entry,
            entropy=entropy,
            churn=churn,
            pressure=pressure,
        ),
    }


def top_risky_ports(root: Path, n: int = 10) -> list[dict[str, Any]]:
    history = load_port_history(root)
    scores = []
    for port_id, entry in history.items():
        snapshot = port_risk_snapshot(entry)
        scores.append({"port_id": port_id, **snapshot})
    return sorted(scores, key=lambda item: item["policy_risk_score"], reverse=True)[:n]


def report_markdown(root: Path, run_id: str | None = None) -> str:
    from hx.parents import top_risky_parents

    lines = ["# hx metrics report", ""]
    if run_id:
        lines.append(f"- run_id: `{run_id}`")
    summary = summarize_runs(root)
    lines.append(
        f"- repo_architecture_potential: {summary['architecture_potential']}"
    )
    lines.append(
        f"- repo_approval_rate: {summary['approval_rate']}"
    )
    for port in top_risky_ports(root, 10):
        lines.append(
            f"- {port['port_id']}: policy_risk={port['policy_risk_score']}, "
            f"entropy_norm={port['entropy']}, entropy_raw={port['entropy_raw']}, "
            f"churn_decay={port['churn']}, churn_raw={port['churn_raw']}, "
            f"pressure={port['pressure']}"
        )
    try:
        hexmap = load_hexmap(root)
        risky_parents = top_risky_parents(root, hexmap, 5)
    except HexMapError:
        risky_parents = []
    if risky_parents:
        lines.append("")
        lines.append("## Parent Risk")
        for parent in risky_parents:
            metrics = parent["metrics"]
            lines.append(
                f"- {parent['parent_id']}: potential={metrics['parent_architecture_potential']}, "
                f"pressure={metrics['parent_boundary_pressure']}, "
                f"cohesion={metrics['parent_cohesion']}"
            )
    return "\n".join(lines) + "\n"


def parent_report(root: Path, parent_id: str) -> str:
    from hx.parents import parent_report_markdown

    hexmap = load_hexmap(root)
    return parent_report_markdown(root, hexmap, parent_id)


def summarize_runs(root: Path) -> dict[str, Any]:
    runs = list_runs(root)
    radius_distribution: dict[int, int] = defaultdict(int)
    proof_coverage = []
    architecture_potential = []
    approval_flags = []
    component_totals: dict[str, list[float]] = defaultdict(list)
    for run in runs:
        if run.radius is not None:
            radius_distribution[run.radius] += 1
        if run.metrics:
            proof_coverage.append(run.metrics.get("proof_coverage", 1.0))
            architecture_potential.append(run.metrics.get("architecture_potential", 0.0))
            components = run.metrics.get("architecture_potential_components", {})
            for name, value in components.items():
                component_totals[name].append(float(value))
            approval_flags.append(1.0 if components.get("approval_rate", 0.0) > 0 else 0.0)
    return {
        "runs": len(runs),
        "radius_distribution": dict(sorted(radius_distribution.items())),
        "avg_proof_coverage": (
            round(sum(proof_coverage) / len(proof_coverage), 3)
            if proof_coverage
            else 1.0
        ),
        "architecture_potential": (
            round(sum(architecture_potential) / len(architecture_potential), 4)
            if architecture_potential
            else 0.0
        ),
        "architecture_potential_components": {
            name: round(sum(values) / len(values), 4)
            for name, values in sorted(component_totals.items())
            if values
        },
        "approval_rate": (
            round(sum(approval_flags) / len(approval_flags), 4)
            if approval_flags
            else 0.0
        ),
    }
