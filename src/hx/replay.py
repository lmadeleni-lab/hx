from __future__ import annotations

from pathlib import Path
from typing import Any

from hx.audit import load_run
from hx.authz import (
    AuthorizationError,
    authorize_path,
)
from hx.authz import (
    allowed_cells as calc_allowed_cells,
)
from hx.hexmap import HexMapError, load_hexmap
from hx.policy import load_policy
from hx.proof import run_allowed_command


def replay_run(root: Path, run_id: str) -> dict[str, Any]:
    run = load_run(root, run_id)
    policy = load_policy(root)
    results = []
    replayed_events = 0
    failed_events = 0
    for event_index, event in enumerate(run.events):
        if event.event_type == "cmd.run":
            command = event.payload["command"]
            active_cell_id = run.active_cell_id
            radius = run.radius
            effective_cwd = event.payload.get("cwd")
            if active_cell_id is None or radius is None:
                failed_events += 1
                results.append(
                    {
                        "event_index": event_index,
                        "ok": False,
                        "command": command,
                        "error": "Missing original active cell or radius; replay denied",
                    }
                )
                continue
            try:
                hexmap = load_hexmap(root)
                original_allowed = calc_allowed_cells(hexmap, active_cell_id, radius)
                if run.allowed_cells and sorted(run.allowed_cells) != original_allowed:
                    raise AuthorizationError(
                        "Original allowed cell context is inconsistent with the current hex map"
                    )
                if effective_cwd:
                    authorize_path(
                        root,
                        hexmap,
                        policy,
                        active_cell_id,
                        radius,
                        effective_cwd.rstrip("/") + "/dummy",
                    )
                result = run_allowed_command(root, policy, command, cwd=effective_cwd)
                replayed_events += 1
                results.append({"event_index": event_index, "ok": True, **result})
            except (AuthorizationError, HexMapError, FileNotFoundError, PermissionError) as exc:
                failed_events += 1
                results.append(
                    {
                        "event_index": event_index,
                        "ok": False,
                        "command": command,
                        "cwd": effective_cwd,
                        "error": str(exc),
                    }
                )
    return {
        "run_id": run_id,
        "replayed_events": replayed_events,
        "failed_events": failed_events,
        "results": results,
    }
