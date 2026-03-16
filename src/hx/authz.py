from __future__ import annotations

from collections import deque
from pathlib import Path

from hx.hexmap import resolve_cell_id
from hx.models import HexMap
from hx.policy import path_allowed


class AuthorizationError(PermissionError):
    pass


def allowed_cells(hexmap: HexMap, active_cell_id: str, radius: int) -> list[str]:
    seen = {active_cell_id}
    queue: deque[tuple[str, int]] = deque([(active_cell_id, 0)])
    while queue:
        cell_id, depth = queue.popleft()
        if depth >= radius:
            continue
        cell = hexmap.cell(cell_id)
        for neighbor in cell.neighbors:
            if neighbor and neighbor not in seen:
                seen.add(neighbor)
                queue.append((neighbor, depth + 1))
    return sorted(seen)


def authorize_path(
    root: Path,
    hexmap: HexMap,
    policy: dict,
    active_cell_id: str,
    radius: int,
    path: str,
) -> str:
    _ = root
    rel = str(Path(path))
    if not path_allowed(policy, rel):
        raise AuthorizationError(f"Path denied by policy sandbox: {rel}")
    cell_id = resolve_cell_id(hexmap, rel)
    if cell_id is None:
        raise AuthorizationError(f"Path is outside the declared hexmap: {rel}")
    if cell_id not in allowed_cells(hexmap, active_cell_id, radius):
        raise AuthorizationError(
            f"Path {rel} belongs to cell {cell_id}, outside allowed radius from {active_cell_id}"
        )
    return cell_id


def authorize_paths(
    root: Path,
    hexmap: HexMap,
    policy: dict,
    active_cell_id: str,
    radius: int,
    paths: list[str],
) -> dict[str, str]:
    return {
        path: authorize_path(root, hexmap, policy, active_cell_id, radius, path)
        for path in paths
    }
