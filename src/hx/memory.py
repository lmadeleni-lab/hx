from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hx.audit import list_runs, now_iso
from hx.config import STATE_DIR, TASK_DIR, ensure_hx_dirs
from hx.hexmap import HexMapError, load_hexmap
from hx.metrics import summarize_runs, top_risky_ports
from hx.models import TaskState
from hx.parents import parent_groups_overview, parent_summary, resolve_parent_group

REPO_SUMMARY = "repo_summary.json"
PARENT_SUMMARIES = "parent_summaries.json"
CELL_SUMMARIES = "cell_summaries.json"
OPEN_THREADS = "open_threads.json"
SESSION_SUMMARY = "session_summary.json"


def _state_path(root: Path, filename: str) -> Path:
    ensure_hx_dirs(root)
    return root / STATE_DIR / filename


def _write_state(root: Path, filename: str, payload: dict[str, Any] | list[Any]) -> Path:
    path = _state_path(root, filename)
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return path


def _load_state_if_exists(root: Path, filename: str) -> dict[str, Any] | list[Any] | None:
    path = _state_path(root, filename)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _load_tasks(root: Path) -> list[TaskState]:
    base = root / TASK_DIR
    if not base.exists():
        return []
    tasks = []
    for path in sorted(base.glob("*.json")):
        tasks.append(TaskState.from_dict(json.loads(path.read_text())))
    return tasks


def _recent_runs_payload(root: Path, limit: int = 5) -> list[dict[str, Any]]:
    runs = sorted(list_runs(root), key=lambda run: run.started_at, reverse=True)
    recent = []
    for run in runs[:limit]:
        recent.append(
            {
                "run_id": run.run_id,
                "command": run.command,
                "status": run.status,
                "active_cell_id": run.active_cell_id,
                "radius": run.radius,
                "started_at": run.started_at,
                "finished_at": run.finished_at,
            }
        )
    return recent


def _cell_summaries(root: Path) -> list[dict[str, Any]]:
    try:
        hexmap = load_hexmap(root)
    except HexMapError:
        return []

    recent_runs = list_runs(root)
    risky_ports = top_risky_ports(root, 50)
    risky_by_port = {item["port_id"]: item for item in risky_ports}
    summaries = []
    for cell in hexmap.cells:
        parent_info = resolve_parent_group(hexmap, cell.cell_id)
        cell_port_ids = [port.port_id for port in cell.ports if port is not None]
        relevant_runs = []
        for run in sorted(recent_runs, key=lambda run: run.started_at, reverse=True):
            if run.active_cell_id == cell.cell_id or cell.cell_id in run.allowed_cells:
                relevant_runs.append(
                    {
                        "run_id": run.run_id,
                        "command": run.command,
                        "status": run.status,
                        "started_at": run.started_at,
                    }
                )
            if len(relevant_runs) >= 5:
                break
        summaries.append(
            {
                "cell_id": cell.cell_id,
                "summary": cell.summary,
                "invariants": cell.invariants,
                "tests": cell.tests,
                "neighbors": cell.neighbors,
                "parent": parent_info,
                "risky_ports": [
                    risky_by_port[port_id]
                    for port_id in cell_port_ids
                    if port_id in risky_by_port
                ],
                "recent_runs": relevant_runs,
            }
        )
    return summaries


def _parent_summaries(root: Path) -> list[dict[str, Any]]:
    try:
        hexmap = load_hexmap(root)
    except HexMapError:
        return []
    return [
        parent_summary(root, hexmap, item["parent_id"])
        for item in parent_groups_overview(root, hexmap)
    ]


def _open_threads(root: Path) -> dict[str, Any]:
    tasks = _load_tasks(root)
    pending_tasks = [
        {
            "task_id": task.task_id,
            "status": task.status,
            "active_cell_id": task.active_cell_id,
            "radius": task.radius,
            "requires_approval": bool(task.port_check.get("requires_approval")),
            "proof_ok": bool(task.proofs.get("verification", {}).get("ok", False)),
            "audit_run_id": task.audit_run_id,
        }
        for task in tasks
        if task.status not in {"committed", "aborted"}
    ]
    failed_runs = [
        {
            "run_id": run.run_id,
            "command": run.command,
            "status": run.status,
            "active_cell_id": run.active_cell_id,
        }
        for run in sorted(list_runs(root), key=lambda run: run.started_at, reverse=True)
        if run.status in {"failed", "error"}
    ][:5]
    return {
        "pending_tasks": pending_tasks,
        "failed_runs": failed_runs,
    }


def _recommended_next_actions(
    open_threads: dict[str, Any],
    risky_ports: list[dict[str, Any]],
    risky_parents: list[dict[str, Any]],
) -> list[str]:
    actions: list[str] = []
    if open_threads["pending_tasks"]:
        task = open_threads["pending_tasks"][0]
        actions.append(
            f"Resume task {task['task_id']} in cell {task['active_cell_id'] or 'unknown'}."
        )
    if open_threads["failed_runs"]:
        run = open_threads["failed_runs"][0]
        actions.append(f"Inspect failed run {run['run_id']} ({run['command']}).")
    if risky_parents:
        actions.append(f"Review risky parent {risky_parents[0]['parent_id']}.")
    if risky_ports:
        actions.append(f"Review risky port {risky_ports[0]['port_id']}.")
    if not actions:
        actions.append("Start from `hx hex show <cell_id>` or `hx resume`.")
    return actions


def summarize_memory(root: Path) -> dict[str, Any]:
    ensure_hx_dirs(root)
    state_runs = summarize_runs(root)
    risky_ports = top_risky_ports(root, 10)
    try:
        hexmap = load_hexmap(root)
        risky_parents = parent_groups_overview(root, hexmap)
        risky_parents = sorted(
            risky_parents,
            key=lambda item: item["metrics"]["parent_architecture_potential"],
            reverse=True,
        )[:10]
    except HexMapError:
        risky_parents = []
    cell_summaries = _cell_summaries(root)
    parent_summaries = _parent_summaries(root)
    open_threads = _open_threads(root)
    session_summary = {
        "generated_at": now_iso(),
        "recent_runs": _recent_runs_payload(root),
        "resume_candidates": [
            {
                "task_id": task["task_id"],
                "active_cell_id": task["active_cell_id"],
                "reason": "pending task",
            }
            for task in open_threads["pending_tasks"][:3]
        ],
    }
    repo_summary = {
        "generated_at": now_iso(),
        "runs": state_runs["runs"],
        "radius_distribution": state_runs["radius_distribution"],
        "avg_proof_coverage": state_runs["avg_proof_coverage"],
        "architecture_potential": state_runs["architecture_potential"],
        "approval_rate": state_runs["approval_rate"],
        "top_risky_ports": risky_ports[:5],
        "top_risky_parents": [
            {
                "parent_id": item["parent_id"],
                "center_cell_id": item["center_cell_id"],
                "metrics": item["metrics"],
            }
            for item in risky_parents[:5]
        ],
        "open_thread_counts": {
            "pending_tasks": len(open_threads["pending_tasks"]),
            "failed_runs": len(open_threads["failed_runs"]),
        },
        "recommended_next_actions": _recommended_next_actions(
            open_threads,
            risky_ports,
            risky_parents,
        ),
        "compaction_policy": {
            "storage_model": "raw audit + derived summaries",
            "authorization_primitive": "cell",
            "parent_role": "coarse-grained planning and summarization",
        },
    }

    _write_state(root, REPO_SUMMARY, repo_summary)
    _write_state(root, PARENT_SUMMARIES, parent_summaries)
    _write_state(root, CELL_SUMMARIES, cell_summaries)
    _write_state(root, OPEN_THREADS, open_threads)
    _write_state(root, SESSION_SUMMARY, session_summary)

    return {
        "repo_summary": repo_summary,
        "parent_summaries": parent_summaries,
        "cell_summaries": cell_summaries,
        "open_threads": open_threads,
        "session_summary": session_summary,
    }


def memory_status(root: Path) -> dict[str, Any]:
    files = {}
    for filename in [
        REPO_SUMMARY,
        PARENT_SUMMARIES,
        CELL_SUMMARIES,
        OPEN_THREADS,
        SESSION_SUMMARY,
    ]:
        path = _state_path(root, filename)
        files[filename] = {
            "exists": path.exists(),
            "path": str(path),
        }
        if path.exists():
            files[filename]["mtime_ns"] = path.stat().st_mtime_ns

    repo_summary = _load_state_if_exists(root, REPO_SUMMARY)
    open_threads = _load_state_if_exists(root, OPEN_THREADS) or {
        "pending_tasks": [],
        "failed_runs": [],
    }
    return {
        "files": files,
        "repo_summary_available": repo_summary is not None,
        "pending_tasks": len(open_threads.get("pending_tasks", [])),
        "failed_runs": len(open_threads.get("failed_runs", [])),
    }


def resume_context(root: Path) -> dict[str, Any]:
    repo_summary = _load_state_if_exists(root, REPO_SUMMARY)
    open_threads = _load_state_if_exists(root, OPEN_THREADS)
    session_summary = _load_state_if_exists(root, SESSION_SUMMARY)
    cell_summaries = _load_state_if_exists(root, CELL_SUMMARIES)
    if repo_summary is None or open_threads is None or session_summary is None:
        generated = summarize_memory(root)
        repo_summary = generated["repo_summary"]
        open_threads = generated["open_threads"]
        session_summary = generated["session_summary"]
        cell_summaries = generated["cell_summaries"]

    focus_cells = []
    for item in session_summary.get("resume_candidates", []):
        if item.get("active_cell_id"):
            focus_cells.append(item["active_cell_id"])
    if not focus_cells and cell_summaries:
        focus_cells = [cell_summaries[0]["cell_id"]]

    return {
        "repo_summary": repo_summary,
        "open_threads": open_threads,
        "session_summary": session_summary,
        "focus_cells": focus_cells,
    }
