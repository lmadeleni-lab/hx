from __future__ import annotations

import ast
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from hx.audit import append_event, update_run
from hx.authz import allowed_cells as calc_allowed_cells
from hx.authz import authorize_paths
from hx.config import STATE_DIR
from hx.hexmap import load_hexmap, resolve_cell_id
from hx.metrics import load_port_history, port_risk_snapshot
from hx.models import Cell, HexMap, Port
from hx.policy import (
    current_mode,
    load_policy,
    require_human_for_breaking,
    strict_risk_threshold,
)

_SURFACES_CACHE = "surfaces.json"

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


def _typescript_exports(path: Path) -> dict[str, Any]:
    """Basic TypeScript/JavaScript export extraction via regex."""
    try:
        text = path.read_text()
    except (UnicodeDecodeError, OSError):
        return {"exports": [], "signatures": {}}
    exports: list[str] = []
    signatures: dict[str, str] = {}
    # export function foo(...) / export async function foo(...)
    for match in re.finditer(
        r"export\s+(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)", text
    ):
        name, args = match.group(1), match.group(2).strip()
        exports.append(name)
        signatures[name] = f"{name}({args})"
    # export class Foo
    for match in re.finditer(r"export\s+class\s+(\w+)", text):
        name = match.group(1)
        exports.append(name)
        signatures[name] = f"class {name}"
    # export const/let/var foo
    for match in re.finditer(r"export\s+(?:const|let|var)\s+(\w+)", text):
        name = match.group(1)
        if name not in exports:
            exports.append(name)
            signatures[name] = f"const {name}"
    # export default
    for match in re.finditer(r"export\s+default\s+(?:class|function)?\s*(\w+)", text):
        name = match.group(1)
        if name not in exports:
            exports.append(name)
            signatures[name] = f"default {name}"
    return {"exports": sorted(set(exports)), "signatures": signatures}


def _go_exports(path: Path) -> dict[str, Any]:
    """Basic Go export extraction - exported names start with uppercase."""
    try:
        text = path.read_text()
    except (UnicodeDecodeError, OSError):
        return {"exports": [], "signatures": {}}
    exports: list[str] = []
    signatures: dict[str, str] = {}
    func_re = r"^func\s+(?:\([^)]*\)\s+)?([A-Z]\w*)\s*\(([^)]*)\)"
    for match in re.finditer(func_re, text, re.MULTILINE):
        name, args = match.group(1), match.group(2).strip()
        exports.append(name)
        signatures[name] = f"{name}({args})"
    for match in re.finditer(r"^type\s+([A-Z]\w*)\s+", text, re.MULTILINE):
        name = match.group(1)
        exports.append(name)
        signatures[name] = f"type {name}"
    return {"exports": sorted(set(exports)), "signatures": signatures}


SURFACE_EXTRACTORS: dict[str, Any] = {
    ".py": _python_exports,
    ".ts": _typescript_exports,
    ".tsx": _typescript_exports,
    ".js": _typescript_exports,
    ".jsx": _typescript_exports,
    ".mjs": _typescript_exports,
    ".go": _go_exports,
}

SCHEMA_EXTENSIONS = {".json", ".proto", ".sql", ".graphql", ".avsc"}


def _load_surface_cache(root: Path) -> dict[str, Any]:
    path = root / STATE_DIR / _SURFACES_CACHE
    if path.exists():
        return json.loads(path.read_text())
    return {}


def _save_surface_cache(root: Path, cache: dict[str, Any]) -> None:
    path = root / STATE_DIR / _SURFACES_CACHE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2) + "\n")


def rebuild_surface_cache(root: Path, hexmap: HexMap) -> dict[str, Any]:
    """Rebuild and persist the surface cache for all cells."""
    cache: dict[str, Any] = {}
    for cell in hexmap.cells:
        cache[cell.cell_id] = extract_cell_surface(root, cell)
    _save_surface_cache(root, cache)
    return cache


def extract_cell_surface(root: Path, cell: Cell) -> dict[str, Any]:
    exports: set[str] = set()
    signatures: dict[str, str] = {}
    schemas: list[str] = []
    unsupported_extensions: set[str] = set()
    for pattern in cell.paths:
        effective = pattern + "/*" if pattern.endswith("**") else pattern
        for path in root.glob(effective):
            if path.is_dir():
                continue
            extractor = SURFACE_EXTRACTORS.get(path.suffix)
            if extractor is not None:
                surface = extractor(path)
                exports.update(surface["exports"])
                signatures.update(surface["signatures"])
            elif path.suffix in SCHEMA_EXTENSIONS:
                schemas.append(str(path.relative_to(root)))
            elif path.suffix and path.suffix not in {
                ".md", ".txt", ".toml", ".yaml", ".yml", ".cfg",
                ".ini", ".lock", ".gitignore", ".dockerignore",
                ".csv", ".png", ".jpg", ".gif", ".svg", ".ico",
            }:
                unsupported_extensions.add(path.suffix)
    return {
        "cell_id": cell.cell_id,
        "exports": sorted(exports),
        "signatures": signatures,
        "schemas": sorted(schemas),
        "invariants": cell.invariants,
        "tests": cell.tests,
        "unsupported_extensions": sorted(unsupported_extensions),
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
    # Use cached surface if available
    cache = _load_surface_cache(root)
    if cell_id in cache:
        surface = dict(cache[cell_id])
    else:
        surface = extract_cell_surface(root, cell)
    if port and port.surface.declared_exports:
        surface["exports"] = sorted(set(port.surface.declared_exports))
    return surface


def find_triangles(hexmap: HexMap) -> list[tuple[str, str, str]]:
    """Find all triangular cycles (A,B,C) in the hex neighbor graph."""
    triangles: list[tuple[str, str, str]] = []
    cell_ids = sorted(c.cell_id for c in hexmap.cells)
    id_set = set(cell_ids)
    seen: set[tuple[str, ...]] = set()

    for a in cell_ids:
        a_neighbors = {
            n for n in hexmap.cell(a).neighbors if n is not None and n in id_set
        }
        for b in a_neighbors:
            b_neighbors = {
                n for n in hexmap.cell(b).neighbors
                if n is not None and n in id_set
            }
            common = a_neighbors & b_neighbors
            for c in common:
                tri = tuple(sorted([a, b, c]))
                if tri not in seen:
                    seen.add(tri)
                    triangles.append((tri[0], tri[1], tri[2]))
    return triangles


def _find_port_between(
    hexmap: HexMap, from_cell: str, to_cell: str,
) -> Port | None:
    """Find the port on from_cell that faces to_cell."""
    cell = hexmap.cell(from_cell)
    for i, neighbor in enumerate(cell.neighbors):
        if neighbor == to_cell:
            port = cell.ports[i] if i < len(cell.ports) else None
            return port
    return None


def dual_port_check(
    hexmap: HexMap, cell_id: str, side_index: int,
) -> list[str]:
    """Check port duality and orientation consistency.

    Validates:
    - If both sides export the same symbol (non-orientable)
    - If a port exists but has no reverse port on the neighbor
    - If export/import pairing is inconsistent
    """
    warnings: list[str] = []
    cell = hexmap.cell(cell_id)
    port = cell.ports[side_index] if side_index < len(cell.ports) else None
    neighbor_id = cell.neighbors[side_index]
    if port is None or neighbor_id is None:
        return warnings

    exports = set(port.surface.declared_exports)

    # Find the reverse port on the neighbor
    reverse_port = _find_port_between(hexmap, neighbor_id, cell_id)

    # Check: port exists but no reverse port (gauge defect)
    if reverse_port is None and exports:
        warnings.append(
            f"{cell_id}[{side_index}]->{neighbor_id}: "
            f"exports {sorted(exports)} but no reverse port exists"
        )
        return warnings

    if reverse_port is None:
        return warnings

    neighbor_exports = set(reverse_port.surface.declared_exports)

    # Check: both sides export the same symbol (non-orientable)
    overlap = exports & neighbor_exports
    if overlap:
        both_export = (
            port.direction == "export"
            and reverse_port.direction == "export"
        )
        if both_export:
            warnings.append(
                f"{cell_id}[{side_index}]<->{neighbor_id}: "
                f"both sides export {sorted(overlap)} — "
                f"potential non-orientable boundary"
            )

    return warnings


def holonomy_check(
    hexmap: HexMap,
    cycle: tuple[str, ...],
) -> list[str]:
    """Check export consistency around a cycle of cells.

    For a cycle (A, B, C), verifies that port contracts compose
    consistently around the loop (cocycle condition). Checks:
    1. Transitivity: exports at edge i should propagate to edge i+1
    2. Cocycle: direct A->C contract matches composed A->B->C path
    Returns warning strings (empty = consistent).
    """
    warnings: list[str] = []
    if len(cycle) < 3:
        return warnings

    # Collect exports along each directed edge of the cycle
    edge_exports: list[set[str]] = []
    for i in range(len(cycle)):
        from_cell = cycle[i]
        to_cell = cycle[(i + 1) % len(cycle)]
        port = _find_port_between(hexmap, from_cell, to_cell)
        if port is not None:
            edge_exports.append(set(port.surface.declared_exports))
        else:
            edge_exports.append(set())

    # Need at least 2 edges with exports to check composition
    active_edges = [e for e in edge_exports if e]
    if len(active_edges) < 2:
        return warnings

    # Check 1: Transitivity — symbols exported at edge i that
    # are lost at edge i+1 (any amount of loss is a violation)
    for i in range(len(cycle)):
        current = edge_exports[i]
        next_edge = edge_exports[(i + 1) % len(cycle)]
        if current and next_edge:
            lost = current - next_edge
            if lost:
                from_cell = cycle[i]
                mid_cell = cycle[(i + 1) % len(cycle)]
                to_cell = cycle[(i + 2) % len(cycle)]
                warnings.append(
                    f"holonomy: {from_cell}->{mid_cell}->{to_cell}: "
                    f"exports {sorted(lost)} not propagated"
                )

    # Check 2: Cocycle condition — for each pair of non-adjacent
    # cycle vertices, the direct port should be consistent with
    # the composed path through intermediate vertices
    for i in range(len(cycle)):
        a = cycle[i]
        c = cycle[(i + 2) % len(cycle)]
        b = cycle[(i + 1) % len(cycle)]
        # Direct A->C port
        direct_port = _find_port_between(hexmap, a, c)
        direct_exports = (
            set(direct_port.surface.declared_exports)
            if direct_port else set()
        )
        # Composed A->B exports intersected with B->C exports
        ab_exports = edge_exports[i]
        bc_exports = edge_exports[(i + 1) % len(cycle)]
        composed = ab_exports & bc_exports if ab_exports and bc_exports else set()
        # If direct and composed both have content, check consistency
        if direct_exports and composed:
            mismatch = direct_exports.symmetric_difference(composed)
            if mismatch:
                warnings.append(
                    f"cocycle: {a}->{c} direct exports "
                    f"{sorted(direct_exports)} != composed "
                    f"{a}->{b}->{c} exports {sorted(composed)}"
                )
    return warnings


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
    ignored = shutil.ignore_patterns(
        ".hx", ".git", "__pycache__", ".pytest_cache", ".ruff_cache",
        ".env", ".env.*", "secrets", ".secrets", "node_modules",
        "*.pem", "*.key",
    )
    for child in root.iterdir():
        if child.name in {".hx", ".git"}:
            continue
        target = destination / child.name
        if child.is_dir():
            shutil.copytree(child, target, ignore=ignored, symlinks=False)
        else:
            shutil.copy2(child, target)


def apply_patch_in_temp(root: Path, patch_path: Path) -> Path:
    tempdir = Path(tempfile.mkdtemp(prefix="hx-port-"))
    _copy_repo(root, tempdir)
    result = subprocess.run(
        ["git", "apply", str(patch_path)],
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
