from __future__ import annotations

import fcntl
import json
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hx.config import AUDIT_DIR, ensure_hx_dirs
from hx.models import AuditEvent, AuditRun


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def audit_path(root: Path, run_id: str) -> Path:
    return root / AUDIT_DIR / f"{run_id}.json"


@contextmanager
def _locked_file(path: Path, mode: str = "r+") -> Generator:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("{}")
    with open(path, mode) as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield fh
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


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
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(run.to_dict(), indent=2) + "\n")
    tmp.rename(path)
    return path


def load_run(root: Path, run_id: str) -> AuditRun:
    return AuditRun.from_dict(json.loads(audit_path(root, run_id).read_text()))


def append_event(root: Path, run_id: str, event_type: str, payload: dict[str, Any]) -> None:
    path = audit_path(root, run_id)
    with _locked_file(path, "r+") as fh:
        data = json.loads(fh.read())
        run = AuditRun.from_dict(data)
        run.events.append(
            AuditEvent(timestamp=now_iso(), event_type=event_type, payload=payload)
        )
        fh.seek(0)
        fh.truncate()
        fh.write(json.dumps(run.to_dict(), indent=2) + "\n")


def update_run(root: Path, run_id: str, **updates: Any) -> None:
    path = audit_path(root, run_id)
    with _locked_file(path, "r+") as fh:
        data = json.loads(fh.read())
        run = AuditRun.from_dict(data)
        for key, value in updates.items():
            setattr(run, key, value)
        fh.seek(0)
        fh.truncate()
        fh.write(json.dumps(run.to_dict(), indent=2) + "\n")


def finish_run(root: Path, run_id: str, status: str = "ok") -> None:
    path = audit_path(root, run_id)
    with _locked_file(path, "r+") as fh:
        data = json.loads(fh.read())
        run = AuditRun.from_dict(data)
        run.status = status
        run.finished_at = now_iso()
        fh.seek(0)
        fh.truncate()
        fh.write(json.dumps(run.to_dict(), indent=2) + "\n")


def list_runs(root: Path) -> list[AuditRun]:
    base = root / AUDIT_DIR
    if not base.exists():
        return []
    runs = []
    for path in sorted(base.glob("*.json")):
        runs.append(AuditRun.from_dict(json.loads(path.read_text())))
    return runs
