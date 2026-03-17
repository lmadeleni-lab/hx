from __future__ import annotations

import fnmatch
import json
from pathlib import Path

from hx.config import DEFAULT_HEXMAP
from hx.models import Cell, HexMap
from hx.parents import derive_parent_groups, validate_parent_groups

EXCLUDED_TOP_LEVEL = {
    ".git",
    ".github",
    ".hx",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
}


class HexMapError(RuntimeError):
    pass


def load_hexmap(root: Path) -> HexMap:
    path = root / DEFAULT_HEXMAP
    if not path.exists():
        raise HexMapError(f"Missing hexmap file: {path}")
    return HexMap.from_dict(json.loads(path.read_text()))


def save_hexmap(root: Path, hexmap: HexMap) -> Path:
    path = root / DEFAULT_HEXMAP
    path.write_text(json.dumps(hexmap.to_dict(), indent=2) + "\n")
    return path


def build_hexmap(root: Path) -> HexMap:
    existing = None
    path = root / DEFAULT_HEXMAP
    if path.exists():
        try:
            existing = load_hexmap(root)
        except HexMapError:
            existing = None
    cells: list[Cell] = []
    candidates = []
    for child in sorted(root.iterdir()):
        if child.name in EXCLUDED_TOP_LEVEL or child.name.startswith("."):
            continue
        if child.is_dir():
            candidates.append(child.name)
    if not candidates:
        existing_root = None
        if existing is not None:
            try:
                existing_root = existing.cell("root")
            except KeyError:
                existing_root = None
        cells.append(
            Cell(
                cell_id="root",
                # IMPORTANT: use a pattern that includes top-level files like HEXMAP.json.
                # `**/*` does not match top-level paths (no slash) under fnmatch.
                paths=["**"],
                summary=(
                    existing_root.summary if existing_root is not None else "Single-cell repository"
                ),
                invariants=(
                    existing_root.invariants
                    if existing_root is not None
                    else ["Radius expansions must be justified."]
                ),
                tests=existing_root.tests if existing_root is not None else ["pytest -q"],
                neighbors=existing_root.neighbors if existing_root is not None else [None] * 6,
                ports=existing_root.ports if existing_root is not None else [None] * 6,
            )
        )
    else:
        existing_cells = {
            cell.cell_id: cell
            for cell in (existing.cells if existing is not None else [])
        }
        for name in candidates:
            cell_id = name.replace(".", "_")
            prior = existing_cells.get(cell_id)
            cells.append(
                Cell(
                    cell_id=cell_id,
                    paths=[f"{name}/**"],
                    summary=(
                        prior.summary if prior is not None else f"Auto-discovered cell for {name}"
                    ),
                    invariants=prior.invariants if prior is not None else [],
                    tests=prior.tests if prior is not None else ["pytest -q"],
                    neighbors=prior.neighbors if prior is not None else [None] * 6,
                    ports=prior.ports if prior is not None else [None] * 6,
                )
            )
    hexmap = HexMap(
        version="1",
        cells=cells,
        port_types=existing.port_types if existing is not None else {},
        parent_groups=(
            existing.parent_groups if existing is not None else []
        ),
    )
    hexmap.parent_groups = derive_parent_groups(hexmap, hexmap.parent_groups)
    return hexmap


def _pattern_matches(rel_path: str, pattern: str) -> bool:
    # fnmatch follows shell-style globs; it does not give `**/*` the "match everything"
    # semantics many users expect. We support a tiny compatibility shim because older
    # hx versions generated `**/*` for single-cell repos.
    if fnmatch.fnmatch(rel_path, pattern):
        return True
    if pattern == "**/*" and "/" not in rel_path:
        return fnmatch.fnmatch(rel_path, "*")
    if pattern.endswith("/**"):
        prefix = pattern[: -len("/**")]
        return rel_path == prefix or rel_path.startswith(prefix + "/")
    if pattern.endswith("/**/*"):
        prefix = pattern[: -len("/**/*")]
        return rel_path == prefix or rel_path.startswith(prefix + "/")
    return False


def adjacency_summary(
    hexmap: HexMap, cell_ids: list[str],
) -> list[dict[str, str | int]]:
    """Build a sparse adjacency list from the hex graph.

    Returns a list of edge dicts with from, side, to, direction.
    Only includes non-null neighbors within the given cell_ids scope.
    """
    edges: list[dict[str, str | int]] = []
    for cell_id in cell_ids:
        cell = hexmap.cell(cell_id)
        for i, neighbor in enumerate(cell.neighbors):
            if neighbor is None:
                continue
            port = cell.ports[i] if i < len(cell.ports) else None
            direction = port.direction if port else "none"
            edges.append({
                "from": cell_id,
                "side": i,
                "to": neighbor,
                "direction": direction,
            })
    return edges


def resolve_cell_id(hexmap: HexMap, rel_path: str) -> str | None:
    for cell in hexmap.cells:
        if any(_pattern_matches(rel_path, pattern) for pattern in cell.paths):
            return cell.cell_id
    return None


def _is_connected(hexmap: HexMap, cell_ids: list[str] | None = None) -> bool:
    """Check if the given cells (or all cells) form a connected subgraph."""
    ids = cell_ids or [c.cell_id for c in hexmap.cells]
    if len(ids) <= 1:
        return True
    id_set = set(ids)
    visited: set[str] = set()
    queue = [ids[0]]
    visited.add(ids[0])
    while queue:
        current = queue.pop()
        cell = hexmap.cell(current)
        for neighbor in cell.neighbors:
            if neighbor in id_set and neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)
    return visited == id_set


def validate_hexmap(root: Path, hexmap: HexMap) -> list[str]:
    errors: list[str] = []
    cell_ids = {cell.cell_id for cell in hexmap.cells}
    for cell in hexmap.cells:
        if len(cell.neighbors) != 6:
            errors.append(f"{cell.cell_id}: neighbors must have length 6")
        if len(cell.ports) != 6:
            errors.append(f"{cell.cell_id}: ports must have length 6")
        for pattern in cell.paths:
            matches = list(root.glob(pattern))
            if not matches:
                errors.append(f"{cell.cell_id}: path pattern has no matches: {pattern}")
        for test_entry in cell.tests:
            if " " not in test_entry:
                matches = list(root.glob(test_entry))
                if not matches:
                    errors.append(f"{cell.cell_id}: test glob has no matches: {test_entry}")
        for index, neighbor in enumerate(cell.neighbors):
            port = cell.ports[index] if index < len(cell.ports) else None
            if neighbor is None and port is not None:
                errors.append(f"{cell.cell_id}: port {index} defined but neighbor is null")
            if neighbor is not None:
                if neighbor not in cell_ids:
                    errors.append(f"{cell.cell_id}: unknown neighbor {neighbor} at side {index}")
                if port and port.neighbor_cell_id not in {neighbor, None}:
                    errors.append(f"{cell.cell_id}: port {index} neighbor mismatch")
                symmetric = False
                for other in hexmap.cells:
                    if other.cell_id != neighbor:
                        continue
                    symmetric = cell.cell_id in other.neighbors
                if not symmetric:
                    errors.append(f"{cell.cell_id}: neighbor {neighbor} is not symmetric")
    # Graph connectivity check
    if len(hexmap.cells) > 1 and not _is_connected(hexmap):
        errors.append("hexmap graph is not connected")

    # Occupation fraction warning (hex percolation threshold)
    from hx.metrics import HEX_PERCOLATION_THRESHOLD, occupation_fraction
    occ = occupation_fraction(hexmap)
    if occ > HEX_PERCOLATION_THRESHOLD:
        errors.append(
            f"port occupation fraction {occ} exceeds hex percolation "
            f"threshold {HEX_PERCOLATION_THRESHOLD} — governance "
            f"boundaries may not contain changes"
        )

    errors.extend(validate_parent_groups(hexmap))
    return errors
