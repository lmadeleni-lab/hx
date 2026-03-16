from __future__ import annotations

import ast
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from hx.audit import append_event, update_run
from hx.authz import allowed_cells as calc_allowed_cells
from hx.authz import authorize_paths
from hx.hexmap import load_hexmap, resolve_cell_id
from hx.metrics import load_port_history, port_risk_snapshot
from hx.models import Cell, HexMap, Port
from hx.policy import (
    current_mode,
    load_policy,
    require_human_for_breaking,
    strict_risk_threshold,
)

CHANGE_CATEGORIES = [
    "add_export",
    "remove_export",
    "change_signature",
    "change_schema",
    "change_invariant",
    "change_tests_required",
]

OBLIGATION_WEIGHTS = {
    "port_declared_check": 1.0,
    "cell_escalation_check": 1.25,
    "port_declared_artifact": 0.75,
    "governance_artifact": 0.5,
    "risk_report_artifact": 0.75,
}


def _python_exports(path: Path) -> dict[str, Any]:
    try:
        tree = ast.parse(path.read_text())
    except (SyntaxError, UnicodeDecodeError):
        return {"exports": [], "signatures": {}}
    exports: list[str] = []
    signatures: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            exports.append(node.name)
            args = [arg.arg for arg in node.args.args]
            signatures[node.name] = f"{node.name}({', '.join(args)})"
        elif isinstance(node, ast.ClassDef):
            exports.append(node.name)
            signatures[node.name] = f"class {node.name}"
    return {"exports": sorted(exports), "signatures": signatures}


def extract_cell_surface(root: Path, cell: Cell) -> dict[str, Any]:
    exports: set[str] = set()
    signatures: dict[str, str] = {}
    schemas: list[str] = []
    for pattern in cell.paths:
        for path in root.glob(pattern):
            if path.is_dir():
                continue
            if path.suffix == ".py":
                surface = _python_exports(path)
                exports.update(surface["exports"])
                signatures.update(surface["signatures"])
            if path.suffix in {".json", ".proto", ".sql"}:
                schemas.append(str(path.relative_to(root)))
    return {
        "cell_id": cell.cell_id,
        "exports": sorted(exports),
        "signatures": signatures,
        "schemas": sorted(schemas),
        "invariants": cell.invariants,
        "tests": cell.tests,
    }


def describe_port(hexmap: HexMap, cell_id: str, side_index: int) -> dict[str, Any]:
    cell = hexmap.cell(cell_id)
    port = cell.ports[side_index]
    neighbor = cell.neighbors[side_index]
    return {
        "cell_id": cell_id,
        "side_index": side_index,
        "neighbor_cell_id": neighbor,
        "port_contract": None if port is None else {
            "port_id": port.port_id,
            "direction": port.direction,
            "surface": port.surface.__dict__,
            "invariants": port.invariants,
            "compat": port.compat.__dict__,
            "proof": port.proof.__dict__,
            "approval": port.approval.__dict__,
        },
    }


def port_surface(root: Path, hexmap: HexMap, cell_id: str, side_index: int) -> dict[str, Any]:
    cell = hexmap.cell(cell_id)
    port = cell.ports[side_index]
    surface = extract_cell_surface(root, cell)
    if port and port.surface.declared_exports:
        surface["exports"] = sorted(set(port.surface.declared_exports))
    return surface


def _surface_categories(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    categories: list[str] = []
    before_exports = set(before.get("exports", []))
    after_exports = set(after.get("exports", []))
    if after_exports - before_exports:
        categories.append("add_export")
    if before_exports - after_exports:
        categories.append("remove_export")
    shared = before_exports & after_exports
    if any(
        before.get("signatures", {}).get(name)
        != after.get("signatures", {}).get(name)
        for name in shared
    ):
        categories.append("change_signature")
    if set(before.get("schemas", [])) != set(after.get("schemas", [])):
        categories.append("change_schema")
    if before.get("invariants", []) != after.get("invariants", []):
        categories.append("change_invariant")
    if before.get("tests", []) != after.get("tests", []):
        categories.append("change_tests_required")
    return categories


def _copy_repo(root: Path, destination: Path) -> None:
    ignored = shutil.ignore_patterns(".hx", ".git", "__pycache__", ".pytest_cache", ".ruff_cache")
    for child in root.iterdir():
        if child.name in {".hx"}:
            continue
        target = destination / child.name
        if child.is_dir():
            shutil.copytree(child, target, ignore=ignored)
        else:
            shutil.copy2(child, target)


def apply_patch_in_temp(root: Path, patch_path: Path) -> Path:
    tempdir = Path(tempfile.mkdtemp(prefix="hx-port-"))
    _copy_repo(root, tempdir)
    result = subprocess.run(
        ["git", "apply", "--unsafe-paths", str(patch_path)],
        cwd=tempdir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Unable to apply staged patch in temp repo: {result.stderr.strip()}")
    return tempdir


def impacted_ports(hexmap: HexMap, touched_cells: list[str]) -> list[tuple[str, str, Port]]:
    impacts: list[tuple[str, str, Port]] = []
    touched = set(touched_cells)
    for cell in hexmap.cells:
        for index, port in enumerate(cell.ports):
            if port is None:
                continue
            if cell.cell_id in touched or port.neighbor_cell_id in touched:
                impacts.append((cell.cell_id, f"{cell.cell_id}:{index}", port))
    return impacts


def surface_diff(root: Path, task: dict[str, Any]) -> dict[str, Any]:
    hexmap = load_hexmap(root)
    patch_path = root / str(task["patch_path"])
    tempdir = apply_patch_in_temp(root, patch_path)
    diffs: list[dict[str, Any]] = []
    touched_cells = sorted(
        {
            resolve_cell_id(hexmap, path)
            for path in task.get("files_touched", [])
            if resolve_cell_id(hexmap, path) is not None
        }
    )
    try:
        for cell_id, ref, port in impacted_ports(hexmap, touched_cells):
            if port.neighbor_cell_id is None:
                continue
            before = extract_cell_surface(root, hexmap.cell(cell_id))
            after = extract_cell_surface(tempdir, hexmap.cell(cell_id))
            categories = _surface_categories(before, after)
            diffs.append(
                {
                    "port_ref": ref,
                    "port_id": port.port_id,
                    "cell_id": cell_id,
                    "neighbor_cell_id": port.neighbor_cell_id,
                    "categories": categories,
                    "before_hash": hashlib.sha256(
                        json.dumps(before, sort_keys=True).encode()
                    ).hexdigest(),
                    "after_hash": hashlib.sha256(
                        json.dumps(after, sort_keys=True).encode()
                    ).hexdigest(),
                }
            )
    finally:
        shutil.rmtree(tempdir, ignore_errors=True)
    return {"touched_cells": touched_cells, "diffs": diffs}


def dedupe_specs(specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for spec in specs:
        value = spec["value"]
        existing = merged.get(value)
        if existing is None or spec["weight"] > existing["weight"]:
            merged[value] = spec
    return [merged[value] for value in sorted(merged)]


def check_task_ports(
    root: Path,
    task: dict[str, Any],
    active_cell_id: str,
    radius: int,
) -> dict[str, Any]:
    hexmap = load_hexmap(root)
    policy = load_policy(root)
    history = load_port_history(root)
    cell_map = authorize_paths(
        root,
        hexmap,
        policy,
        active_cell_id,
        radius,
        task["files_touched"],
    )
    diffs = surface_diff(root, task)
    impacted = [item for item in diffs["diffs"] if item["categories"]]
    breaking_categories = {"remove_export", "change_signature", "change_schema"}
    check_specs: list[dict[str, Any]] = []
    artifact_specs: list[dict[str, Any]] = []
    breaking_impacts = []
    for cell_id in set(cell_map.values()):
        cell = hexmap.cell(cell_id)
        for port in cell.ports:
            if port is None:
                continue
            check_specs.extend(
                {
                    "value": check,
                    "class": "port_declared_check",
                    "weight": OBLIGATION_WEIGHTS["port_declared_check"],
                }
                for check in port.proof.required_checks
            )
            artifact_specs.extend(
                {
                    "value": artifact,
                    "class": "port_declared_artifact",
                    "weight": OBLIGATION_WEIGHTS["port_declared_artifact"],
                }
                for artifact in port.proof.required_artifacts
            )
    for impact in impacted:
        if any(category in breaking_categories for category in impact["categories"]):
            breaking_impacts.append(impact)
    risk_details = []
    for impact in impacted:
        entry = history.get(impact["port_id"], {"changes": [], "failures": 0, "touches": 0})
        snapshot = port_risk_snapshot(entry)
        risk_details.append(
            {
                "port_id": impact["port_id"],
                **snapshot,
            }
        )
    threshold = strict_risk_threshold(policy)
    high_risk_ports = [
        detail
        for detail in risk_details
        if threshold is not None and detail["policy_risk_score"] >= threshold
    ]
    classification = "breaking" if breaking_impacts else "compatible"
    requires_approval = bool(breaking_impacts) and require_human_for_breaking(policy)
    approval_reasons = []
    if requires_approval:
        approval_reasons.append("breaking port surface change")
    if current_mode(policy) == "release" and high_risk_ports:
        requires_approval = True
        approval_reasons.append("release mode high-risk port change")
    escalated_cell_ids = sorted(
        {
            cell_id
            for cell_id in (
                {impact["cell_id"] for impact in impacted}
                | {impact["neighbor_cell_id"] for impact in impacted}
            )
            if cell_id is not None
        }
    )
    proof_tier = "standard"
    if high_risk_ports and current_mode(policy) == "release":
        proof_tier = "strict"
    elif breaking_impacts or high_risk_ports:
        proof_tier = "elevated"
    if proof_tier in {"elevated", "strict"}:
        for cell_id in escalated_cell_ids:
            cell = hexmap.cell(cell_id)
            check_specs.extend(
                {
                    "value": check,
                    "class": "cell_escalation_check",
                    "weight": OBLIGATION_WEIGHTS["cell_escalation_check"],
                }
                for check in cell.tests
            )
        artifact_specs.append(
            {
                "value": f".hx/artifacts/{task['task_id']}/port_check.json",
                "class": "governance_artifact",
                "weight": OBLIGATION_WEIGHTS["governance_artifact"],
            }
        )
        artifact_specs.append(
            {
                "value": f".hx/artifacts/{task['task_id']}/surface_diff.json",
                "class": "governance_artifact",
                "weight": OBLIGATION_WEIGHTS["governance_artifact"],
            }
        )
    if proof_tier == "strict":
        artifact_specs.append(
            {
                "value": f".hx/artifacts/{task['task_id']}/risk_report.json",
                "class": "risk_report_artifact",
                "weight": OBLIGATION_WEIGHTS["risk_report_artifact"],
            }
        )
    deduped_check_specs = dedupe_specs(check_specs)
    deduped_artifact_specs = dedupe_specs(artifact_specs)
    result = {
        "classification": classification,
        "impacted_ports": impacted,
        "obligations": {
            "required_checks": [spec["value"] for spec in deduped_check_specs],
            "required_artifacts": [spec["value"] for spec in deduped_artifact_specs],
            "check_specs": deduped_check_specs,
            "artifact_specs": deduped_artifact_specs,
        },
        "proof_tier": proof_tier,
        "requires_approval": requires_approval,
        "approval_reasons": approval_reasons,
        "touched_cells": sorted(set(cell_map.values())),
        "allowed_cells": calc_allowed_cells(hexmap, active_cell_id, radius),
        "cross_cell_imports": max(len(set(cell_map.values())) - 1, 0),
        "mode": current_mode(policy),
        "risk_summary": {
            "policy_threshold": threshold,
            "ports": risk_details,
            "high_risk_ports": high_risk_ports,
            "max_policy_risk_score": max(
                (detail["policy_risk_score"] for detail in risk_details),
                default=0.0,
            ),
            "reporting_note": (
                "Use component metrics for descriptive reporting; "
                "policy_risk_score is for enforcement thresholds."
            ),
        },
    }
    if task.get("audit_run_id"):
        append_event(
            root,
            task["audit_run_id"],
            "port.check",
            {
                "task_id": task["task_id"],
                "active_cell_id": active_cell_id,
                "radius": radius,
                "result": result,
            },
        )
        update_run(
            root,
            task["audit_run_id"],
            active_cell_id=active_cell_id,
            radius=radius,
            allowed_cells=result["allowed_cells"],
            files_touched=task["files_touched"],
            port_impacts=[impact["port_id"] for impact in impacted],
            obligations=result["obligations"]["required_checks"],
        )
    return result
