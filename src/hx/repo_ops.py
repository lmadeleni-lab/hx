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
from hx.patches import PatchFormatError, canonicalize_staged_patch

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
    try:
        canonical_patch = canonicalize_staged_patch(root, patch_unified_diff)
    except PatchFormatError as exc:
        append_event(
            root,
            run_id,
            "repo.stage_patch",
            {"task_id": task_id, "error": str(exc)},
        )
        raise RuntimeError(str(exc)) from exc
    patch_path = _task_patch_path(root, task_id)
    patch_path.write_text(canonical_patch)
    touched = touched_files_from_patch(canonical_patch)
    task = TaskState(
        task_id=task_id,
        patch_sha256=hashlib.sha256(canonical_patch.encode()).hexdigest(),
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
    from hx.memory import summarize_memory

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
    # Rebuild surface cache after applying patch (best-effort)
    try:
        from hx.hexmap import load_hexmap as _load_hm
        from hx.ports import rebuild_surface_cache
        rebuild_surface_cache(root, _load_hm(root))
    except Exception:
        pass
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
    summarize_memory(root)
    return {"task_id": task_id, "status": task.status}


def abort_patch(root: Path, task_id: str) -> dict[str, Any]:
    task = load_task(root, task_id)
    for rel in filter(None, [task.patch_path, f"{TASK_DIR}/{task_id}.json"]):
        path = root / rel
        if path.exists():
            path.unlink()
    return {"task_id": task_id, "aborted": True}


def repo_read(
    root: Path,
    path: str,
    *,
    offset: int = 0,
    limit: int | None = None,
    max_bytes: int = 100_000,
) -> dict[str, Any]:
    """Read a file with optional chunking and size cap.

    Returns a dict with content, metadata, and truncation info.
    """
    full_path = (root / path).resolve()
    if not full_path.is_relative_to(root.resolve()):
        raise PermissionError(f"Path traversal blocked: {path}")
    raw = full_path.read_bytes()
    total_bytes = len(raw)
    text = raw.decode(errors="replace")
    lines = text.splitlines(keepends=True)
    total_lines = len(lines)
    warning = None

    if offset == 0 and limit is None and total_bytes > max_bytes:
        # Auto-truncate large files
        char_budget = max_bytes
        truncated_text = text[:char_budget]
        lines_returned = truncated_text.count("\n")
        warning = (
            f"File is {total_bytes} bytes ({total_lines} lines). "
            f"Showing first ~{lines_returned} lines. "
            f"Use offset/limit to read specific sections."
        )
        return {
            "content": truncated_text,
            "total_lines": total_lines,
            "offset": 0,
            "lines_returned": lines_returned,
            "truncated": True,
            "warning": warning,
        }

    # Apply offset/limit
    sliced = lines[offset: offset + limit if limit else None]
    content = "".join(sliced)

    return {
        "content": content,
        "total_lines": total_lines,
        "offset": offset,
        "lines_returned": len(sliced),
        "truncated": limit is not None and offset + limit < total_lines,
        "warning": warning,
    }


def repo_search(
    root: Path,
    query: str,
    globs: list[str] | None = None,
    path_filter: Any | None = None,
    *,
    max_results: int = 20,
    cell_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Search file contents with result limiting and cell pre-filtering.

    Returns dict with matches, total_count, and capped flag.
    """
    # Use cell_paths for pre-filtering if provided
    raw_patterns = cell_paths or globs or ["**/*"]
    # Ensure patterns match files (append /* if ending with **)
    patterns = []
    for p in raw_patterns:
        patterns.append(p)
        if p.endswith("**"):
            patterns.append(p + "/*")
    results: list[dict[str, Any]] = []
    total_count = 0
    seen_files: set[str] = set()

    for pattern in patterns:
        for file_path in root.glob(pattern):
            if not file_path.is_file():
                continue
            rel_path = str(file_path.relative_to(root))
            if rel_path in seen_files:
                continue
            seen_files.add(rel_path)
            if path_filter is not None and not path_filter(rel_path):
                continue
            try:
                text = file_path.read_text()
            except UnicodeDecodeError:
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                if query in line:
                    total_count += 1
                    if len(results) < max_results:
                        results.append({
                            "path": rel_path,
                            "line": lineno,
                            "text": line.strip()[:200],
                        })
    return {
        "matches": results,
        "total_count": total_count,
        "capped": total_count > max_results,
    }
