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
        sandbox = policy.get("path_sandbox", {})
        denylist = sandbox.get("denylist", [])
        raise AuthorizationError(
            f"Path denied by policy sandbox: {rel}. "
            f"Check POLICY.toml [path_sandbox] denylist: {denylist}"
        )
    cell_id = resolve_cell_id(hexmap, rel)
    if cell_id is None:
        cell_ids = [c.cell_id for c in hexmap.cells]
        raise AuthorizationError(
            f"Path '{rel}' is outside the declared hexmap. "
            f"Known cells: {', '.join(cell_ids)}. "
            f"Run `hx hex build` to regenerate the hexmap."
        )
    allowed = allowed_cells(hexmap, active_cell_id, radius)
    if cell_id not in allowed:
        raise AuthorizationError(
            f"Path '{rel}' belongs to cell '{cell_id}', outside "
            f"allowed radius R{radius} from '{active_cell_id}'. "
            f"Allowed cells: {', '.join(allowed)}. "
            f"Use --radius {radius + 1} or --cell {cell_id} "
            f"to expand scope."
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
