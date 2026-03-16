from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from hx.audit import append_event, finish_run, start_run, update_run
from hx.config import TASK_DIR, ensure_hx_dirs
from hx.metrics import compute_metrics, record_port_change
from hx.models import TaskState

PATCH_FILE_RE = re.compile(r"^(?:\+\+\+ b/|--- a/)(.+)$", re.MULTILINE)


def _task_json_path(root: Path, task_id: str) -> Path:
    return root / TASK_DIR / f"{task_id}.json"


def _task_patch_path(root: Path, task_id: str) -> Path:
    return root / TASK_DIR / f"{task_id}.patch"


def load_task(root: Path, task_id: str) -> TaskState:
    return TaskState.from_dict(json.loads(_task_json_path(root, task_id).read_text()))


def save_task(root: Path, task: TaskState) -> None:
    ensure_hx_dirs(root)
    _task_json_path(root, task.task_id).write_text(json.dumps(task.to_dict(), indent=2) + "\n")


def touched_files_from_patch(patch_unified_diff: str) -> list[str]:
    touched: list[str] = []
    for match in PATCH_FILE_RE.findall(patch_unified_diff):
        path = match.strip()
        if path == "/dev/null":
            continue
        if path not in touched:
            touched.append(path)
    return touched


def _verify_staged_patch_integrity(root: Path, task: TaskState) -> str:
    if task.patch_path is None or task.patch_sha256 is None:
        raise RuntimeError("Commit blocked: staged patch metadata is incomplete")
    patch_path = root / str(task.patch_path)
    try:
        patch_text = patch_path.read_text()
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Commit blocked: staged patch is missing; re-stage and re-run checks"
        ) from exc
    patch_sha256 = hashlib.sha256(patch_text.encode()).hexdigest()
    if patch_sha256 != task.patch_sha256:
        raise RuntimeError(
            "Commit blocked: staged patch changed after analysis; re-stage and re-run checks"
        )
    current_files_touched = touched_files_from_patch(patch_text)
    if current_files_touched != task.files_touched:
        raise RuntimeError(
            "Commit blocked: staged patch touched files changed after analysis; "
            "re-stage and re-run checks"
        )
    return patch_text


def stage_patch(
    root: Path,
    task_id: str,
    patch_unified_diff: str,
    *,
    run_id: str | None = None,
) -> dict[str, Any]:
    ensure_hx_dirs(root)
    if run_id is None:
        run_id = start_run(root, "repo.stage_patch").run_id
    patch_path = _task_patch_path(root, task_id)
    patch_path.write_text(patch_unified_diff)
    touched = touched_files_from_patch(patch_unified_diff)
    task = TaskState(
        task_id=task_id,
        patch_sha256=hashlib.sha256(patch_unified_diff.encode()).hexdigest(),
        patch_path=str(patch_path.relative_to(root)),
        files_touched=touched,
        status="staged",
        audit_run_id=run_id,
    )
    save_task(root, task)
    append_event(
        root,
        run_id,
        "repo.stage_patch",
        {"task_id": task_id, "files_touched": touched},
    )
    return {"task_id": task_id, "patch_sha256": task.patch_sha256, "files_touched": touched}


def diff_task(root: Path, task_id: str) -> str:
    task = load_task(root, task_id)
    return (root / str(task.patch_path)).read_text()


def files_touched(root: Path, task_id: str) -> list[str]:
    return load_task(root, task_id).files_touched


def approve_patch(
    root: Path,
    task_id: str,
    approver: str,
    reason: str,
) -> dict[str, Any]:
    task = load_task(root, task_id)
    task.approvals = {
        "human_approved": True,
        "approver": approver,
        "reason": reason,
    }
    save_task(root, task)
    if task.audit_run_id:
        append_event(
            root,
            task.audit_run_id,
            "repo.approve_patch",
            {
                "task_id": task_id,
                "approver": approver,
                "reason": reason,
            },
        )
        update_run(
            root,
            task.audit_run_id,
            decisions=[
                {
                    "type": "approval",
                    "task_id": task_id,
                    "approver": approver,
                    "reason": reason,
                }
            ],
        )
    return task.approvals


def commit_patch(root: Path, task_id: str) -> dict[str, Any]:
    task = load_task(root, task_id)
    port_check = task.port_check
    verification = task.proofs.get("verification", {})
    if not port_check:
        raise RuntimeError("Port check must run before commit")
    if port_check.get("requires_approval") and not task.approvals.get("human_approved", False):
        reasons = port_check.get("approval_reasons", [])
        reason_suffix = f" ({', '.join(reasons)})" if reasons else ""
        raise RuntimeError(f"Commit blocked: human approval required{reason_suffix}")
    if not verification.get("ok", False):
        raise RuntimeError("Commit blocked: proof obligations are not satisfied")
    _verify_staged_patch_integrity(root, task)
    patch_path = root / str(task.patch_path)
    dry_run = subprocess.run(
        ["git", "apply", "--check", str(patch_path)],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if dry_run.returncode != 0:
        raise RuntimeError(f"Patch dry-run failed: {dry_run.stderr.strip()}")
    apply = subprocess.run(
        ["git", "apply", str(patch_path)],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if apply.returncode != 0:
        raise RuntimeError(f"Patch apply failed: {apply.stderr.strip()}")
    record_port_change(
        root,
        task_id,
        task.port_check.get("impacted_ports", []),
        success=True,
    )
    task.status = "committed"
    task.metrics = compute_metrics(root, task.to_dict())
    save_task(root, task)
    if task.audit_run_id:
        append_event(
            root,
            task.audit_run_id,
            "repo.commit_patch",
            {"task_id": task_id, "files_touched": task.files_touched},
        )
        update_run(
            root,
            task.audit_run_id,
            status="ok",
            files_touched=task.files_touched,
            port_impacts=[
                impact["port_id"] for impact in task.port_check.get("impacted_ports", [])
            ],
            obligations=task.port_check.get("obligations", {}).get("required_checks", []),
            artifacts=task.proofs.get("artifacts", []),
            hashes={"patch_sha256": task.patch_sha256 or ""},
            metrics=task.metrics,
        )
        finish_run(root, task.audit_run_id, "ok")
    return {"task_id": task_id, "status": task.status}


def abort_patch(root: Path, task_id: str) -> dict[str, Any]:
    task = load_task(root, task_id)
    for rel in filter(None, [task.patch_path, f"{TASK_DIR}/{task_id}.json"]):
        path = root / rel
        if path.exists():
            path.unlink()
    return {"task_id": task_id, "aborted": True}


def repo_read(root: Path, path: str) -> str:
    return (root / path).read_text()


def repo_search(
    root: Path,
    query: str,
    globs: list[str] | None = None,
    path_filter: Any | None = None,
) -> list[dict[str, Any]]:
    patterns = globs or ["**/*"]
    results = []
    for pattern in patterns:
        for path in root.glob(pattern):
            if not path.is_file():
                continue
            rel_path = str(path.relative_to(root))
            if path_filter is not None and not path_filter(rel_path):
                continue
            try:
                text = path.read_text()
            except UnicodeDecodeError:
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                if query in line:
                    results.append(
                        {
                            "path": rel_path,
                            "line": lineno,
                            "text": line.strip(),
                        }
                    )
    return results
