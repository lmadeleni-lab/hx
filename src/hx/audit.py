from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hx.config import AUDIT_DIR, ensure_hx_dirs
from hx.models import AuditEvent, AuditRun


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def audit_path(root: Path, run_id: str) -> Path:
    return root / AUDIT_DIR / f"{run_id}.json"


def start_run(
    root: Path,
    command: str,
    *,
    active_cell_id: str | None = None,
    radius: int | None = None,
    allowed: list[str] | None = None,
) -> AuditRun:
    ensure_hx_dirs(root)
    run = AuditRun(
        run_id=str(uuid.uuid4()),
        command=command,
        started_at=now_iso(),
        active_cell_id=active_cell_id,
        radius=radius,
        allowed_cells=allowed or [],
    )
    save_run(root, run)
    return run


def save_run(root: Path, run: AuditRun) -> Path:
    path = audit_path(root, run.run_id)
    path.write_text(json.dumps(run.to_dict(), indent=2) + "\n")
    return path


def load_run(root: Path, run_id: str) -> AuditRun:
    return AuditRun.from_dict(json.loads(audit_path(root, run_id).read_text()))


def append_event(root: Path, run_id: str, event_type: str, payload: dict[str, Any]) -> None:
    run = load_run(root, run_id)
    run.events.append(
        AuditEvent(timestamp=now_iso(), event_type=event_type, payload=payload)
    )
    save_run(root, run)


def update_run(root: Path, run_id: str, **updates: Any) -> None:
    run = load_run(root, run_id)
    for key, value in updates.items():
        setattr(run, key, value)
    save_run(root, run)


def finish_run(root: Path, run_id: str, status: str = "ok") -> None:
    run = load_run(root, run_id)
    run.status = status
    run.finished_at = now_iso()
    save_run(root, run)


def list_runs(root: Path) -> list[AuditRun]:
    base = root / AUDIT_DIR
    if not base.exists():
        return []
    runs = []
    for path in sorted(base.glob("*.json")):
        runs.append(AuditRun.from_dict(json.loads(path.read_text())))
    return runs
