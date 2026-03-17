"""Tool registry: extracted MCP tool implementations callable by both MCP server and agent loop."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hx.audit import append_event, finish_run, start_run, update_run
from hx.authz import allowed_cells as calc_allowed_cells
from hx.authz import authorize_path
from hx.config import ensure_hx_dirs
from hx.hexmap import adjacency_summary, load_hexmap, resolve_cell_id
from hx.metrics import compute_metrics, parent_report, report_markdown, top_risky_ports
from hx.parents import (
    parent_group_context,
    parent_groups_overview,
    parent_summary,
    resolve_parent_group,
)
from hx.policy import default_radius, load_policy
from hx.ports import check_task_ports, describe_port, port_surface, surface_diff
from hx.proof import attach_artifacts, collect_task_proofs, run_allowed_command, verify_task_proofs
from hx.repo_ops import (
    abort_patch,
    approve_patch,
    commit_patch,
    diff_task,
    files_touched,
    load_task,
    repo_read,
    repo_search,
    save_task,
    stage_patch,
)


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict[str, Any]
    fn: Callable[..., dict[str, Any]]


class ToolRegistry:
    """Standalone tool registry usable by both MCP server and agent loop."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._tools: dict[str, ToolDef] = {}
        ensure_hx_dirs(root)
        self._register_all()

    @property
    def root(self) -> Path:
        return self._root

    def all(self) -> list[ToolDef]:
        return list(self._tools.values())

    def get(self, name: str) -> ToolDef | None:
        return self._tools.get(name)

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        tool = self._tools.get(name)
        if tool is None:
            raise KeyError(f"Unknown tool: {name}")
        return tool.fn(**arguments)

    def anthropic_tool_schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "name": t.name.replace(".", "_"),
                "description": t.description,
                "input_schema": {
                    "type": "object",
                    "properties": t.parameters,
                    "required": [
                        k for k, v in t.parameters.items() if not v.get("optional", False)
                    ],
                },
            }
            for t in self._tools.values()
        ]

    def resolve_api_name(self, api_name: str) -> str:
        """Map 'hex_resolve_cell' back to 'hex.resolve_cell'."""
        for name in self._tools:
            if name.replace(".", "_") == api_name:
                return name
        raise KeyError(f"No tool matches API name: {api_name}")

    def _register(self, tool: ToolDef) -> None:
        self._tools[tool.name] = tool

    def _default_cwd(self, active_cell_id: str) -> str | None:
        hexmap = load_hexmap(self._root)
        cell = hexmap.cell(active_cell_id)
        for pattern in cell.paths:
            for path in self._root.glob(pattern):
                if path.is_dir():
                    return str(path.relative_to(self._root))
                return str(path.parent.relative_to(self._root))
        return None

    def _register_all(self) -> None:
        base = self._root

        self._register(ToolDef(
            name="hex.resolve_cell",
            description="Resolve a file path to the cell_id that owns it.",
            parameters={"path": {"type": "string", "description": "Relative file path"}},
            fn=lambda path: {"cell_id": resolve_cell_id(load_hexmap(base), path)},
        ))

        self._register(ToolDef(
            name="hex.allowed_cells",
            description="List cell IDs reachable from active_cell_id within the given radius.",
            parameters={
                "active_cell_id": {"type": "string", "description": "Active cell ID"},
                "radius": {"type": "integer", "description": "Expansion radius"},
            },
            fn=lambda active_cell_id, radius: {
                "cells": calc_allowed_cells(load_hexmap(base), active_cell_id, radius)
            },
        ))

        def _hex_context(
            active_cell_id: str, radius: int, detail: str = "summary",
        ) -> dict[str, Any]:
            hexmap = load_hexmap(base)
            allowed = calc_allowed_cells(hexmap, active_cell_id, radius)

            if detail == "summary":
                # Cheap: counts + sparse graph only
                file_count = 0
                for cell_id in allowed:
                    cell = hexmap.cell(cell_id)
                    for pattern in cell.paths:
                        file_count += sum(
                            1 for p in base.glob(pattern) if p.is_file()
                        )
                edges = adjacency_summary(hexmap, allowed)
                return {
                    "cell_count": len(allowed),
                    "file_count": file_count,
                    "cells": [
                        {"cell_id": cid, "summary": hexmap.cell(cid).summary}
                        for cid in allowed
                    ],
                    "graph": [
                        f"{e['from']}[{e['side']}]->{e['to']}"
                        for e in edges
                    ],
                    "detail": "summary",
                    "hint": (
                        "Use detail='full' for complete file list "
                        "and port details."
                    ),
                }

            # detail == "full" — existing behavior
            files: list[str] = []
            summaries: list[dict[str, Any]] = []
            ports: list[dict[str, Any]] = []
            for cell_id in allowed:
                cell = hexmap.cell(cell_id)
                summaries.append({
                    "cell_id": cell.cell_id,
                    "summary": cell.summary,
                    "invariants": cell.invariants,
                })
                for pattern in cell.paths:
                    files.extend(
                        str(p.relative_to(base))
                        for p in base.glob(pattern) if p.is_file()
                    )
                for index in range(6):
                    ports.append(describe_port(hexmap, cell_id, index))
            return {
                "files": sorted(set(files)),
                "summaries": summaries,
                "ports": ports,
                "detail": "full",
            }

        self._register(ToolDef(
            name="hex.context",
            description=(
                "Load cell context. Default 'summary' mode returns counts "
                "and graph. Use detail='full' for files and ports."
            ),
            parameters={
                "active_cell_id": {"type": "string", "description": "Active cell ID"},
                "radius": {"type": "integer", "description": "Expansion radius"},
                "detail": {
                    "type": "string",
                    "description": "'summary' (default) or 'full'",
                    "optional": True,
                },
            },
            fn=_hex_context,
        ))

        self._register(ToolDef(
            name="hex.neighbors",
            description="List the 6 neighbors of a cell.",
            parameters={"cell_id": {"type": "string", "description": "Cell ID"}},
            fn=lambda cell_id: {
                "ports": [
                    {"side_index": i, "neighbor_cell_id": n}
                    for i, n in enumerate(load_hexmap(base).cell(cell_id).neighbors)
                ]
            },
        ))

        def _radius_expand(
            active_cell_id: str, from_radius: int, to_radius: int, justification: str,
        ) -> dict[str, Any]:
            policy = load_policy(base)
            approved = to_radius <= default_radius(policy) and bool(justification.strip())
            return {
                "approved": approved,
                "reason": "auto-approved" if approved
                else "policy threshold exceeded or missing justification",
            }

        self._register(ToolDef(
            name="hex.radius_expand_request",
            description=(
                "Request a radius expansion with justification. "
                "Auto-approves within policy limit."
            ),
            parameters={
                "active_cell_id": {"type": "string", "description": "Active cell ID"},
                "from_radius": {"type": "integer", "description": "Current radius"},
                "to_radius": {"type": "integer", "description": "Requested radius"},
                "justification": {"type": "string", "description": "Why expansion is needed"},
            },
            fn=_radius_expand,
        ))

        self._register(ToolDef(
            name="hex.parent_groups",
            description="Overview of all parent groups with metrics.",
            parameters={},
            fn=lambda: {"parents": parent_groups_overview(base, load_hexmap(base))},
        ))

        def _parent_resolve(cell_id: str) -> dict[str, Any]:
            resolved = resolve_parent_group(load_hexmap(base), cell_id)
            if resolved is None:
                raise KeyError(f"No parent group found for cell {cell_id}")
            return resolved

        self._register(ToolDef(
            name="hex.parent_resolve",
            description="Resolve which parent group a cell belongs to.",
            parameters={"cell_id": {"type": "string", "description": "Cell ID"}},
            fn=_parent_resolve,
        ))

        self._register(ToolDef(
            name="hex.parent_neighbors",
            description="List derived neighbors of a parent group.",
            parameters={"parent_id": {"type": "string", "description": "Parent group ID"}},
            fn=lambda parent_id: {
                "neighbors": parent_summary(base, load_hexmap(base), parent_id)["derived_neighbors"]
            },
        ))

        def _parent_context(parent_id: str) -> dict[str, Any]:
            hexmap = load_hexmap(base)
            ctx = parent_group_context(hexmap, parent_id)
            summ = parent_summary(base, hexmap, parent_id)
            return {
                "cells": ctx["cells"],
                "summaries": summ["child_summaries"],
                "boundary_ports": summ["boundary_ports"],
                "risks": summ["risky_ports"],
            }

        self._register(ToolDef(
            name="hex.parent_context",
            description="Load parent group context: cells, summaries, boundary ports, risks.",
            parameters={"parent_id": {"type": "string", "description": "Parent group ID"}},
            fn=_parent_context,
        ))

        self._register(ToolDef(
            name="hex.parent_summary",
            description="Full parent group summary with metrics, risky ports, and children.",
            parameters={"parent_id": {"type": "string", "description": "Parent group ID"}},
            fn=lambda parent_id: parent_summary(base, load_hexmap(base), parent_id),
        ))

        self._register(ToolDef(
            name="port.describe",
            description="Describe a port at a given side index of a cell.",
            parameters={
                "cell_id": {"type": "string", "description": "Cell ID"},
                "side_index": {"type": "integer", "description": "Side index (0-5)"},
            },
            fn=lambda cell_id, side_index: describe_port(
                load_hexmap(base), cell_id, side_index
            ),
        ))

        self._register(ToolDef(
            name="port.surface",
            description="Extract the current port surface from source files.",
            parameters={
                "cell_id": {"type": "string", "description": "Cell ID"},
                "side_index": {"type": "integer", "description": "Side index (0-5)"},
            },
            fn=lambda cell_id, side_index: port_surface(
                base, load_hexmap(base), cell_id, side_index
            ),
        ))

        self._register(ToolDef(
            name="port.surface_diff",
            description="Compare current surface vs port specification for a staged task.",
            parameters={"task_id": {"type": "string", "description": "Task ID"}},
            fn=lambda task_id: surface_diff(base, load_task(base, task_id).to_dict()),
        ))

        def _port_check(task_id: str, active_cell_id: str, radius: int) -> dict[str, Any]:
            task = load_task(base, task_id)
            task.active_cell_id = active_cell_id
            task.radius = radius
            task.port_check = check_task_ports(base, task.to_dict(), active_cell_id, radius)
            save_task(base, task)
            return task.port_check

        self._register(ToolDef(
            name="port.check",
            description=(
                "Run port impact analysis on a staged patch. "
                "Determines if approval is needed."
            ),
            parameters={
                "task_id": {"type": "string", "description": "Task ID"},
                "active_cell_id": {"type": "string", "description": "Active cell ID"},
                "radius": {"type": "integer", "description": "Expansion radius"},
            },
            fn=_port_check,
        ))

        def _repo_read(
            active_cell_id: str,
            radius: int,
            path: str,
            offset: int = 0,
            limit: int | None = None,
        ) -> dict[str, Any]:
            hexmap = load_hexmap(base)
            policy = load_policy(base)
            authorize_path(base, hexmap, policy, active_cell_id, radius, path)
            result = repo_read(base, path, offset=offset, limit=limit)
            result["path"] = path
            return result

        self._register(ToolDef(
            name="repo.read",
            description=(
                "Read a file with optional chunking. "
                "Large files auto-truncate; use offset/limit to page."
            ),
            parameters={
                "active_cell_id": {"type": "string", "description": "Active cell ID"},
                "radius": {"type": "integer", "description": "Expansion radius"},
                "path": {"type": "string", "description": "Relative file path to read"},
                "offset": {
                    "type": "integer",
                    "description": "Start line (0-based)",
                    "optional": True,
                },
                "limit": {
                    "type": "integer",
                    "description": "Max lines to return",
                    "optional": True,
                },
            },
            fn=_repo_read,
        ))

        def _repo_search(
            active_cell_id: str,
            radius: int,
            query: str,
            globs: list[str] | None = None,
            max_results: int = 20,
        ) -> dict[str, Any]:
            hexmap = load_hexmap(base)
            policy = load_policy(base)
            allowed = calc_allowed_cells(hexmap, active_cell_id, radius)

            # Pre-filter to cell paths
            cell_paths: list[str] = []
            for cid in allowed:
                cell_paths.extend(hexmap.cell(cid).paths)

            def is_authorized(rel_path: str) -> bool:
                try:
                    authorize_path(
                        base, hexmap, policy,
                        active_cell_id, radius, rel_path,
                    )
                    return True
                except PermissionError:
                    return False

            return repo_search(
                base, query, globs,
                path_filter=is_authorized,
                max_results=max_results,
                cell_paths=cell_paths,
            )

        self._register(ToolDef(
            name="repo.search",
            description=(
                "Search file contents within authorized scope. "
                "Returns max 20 results with total_count."
            ),
            parameters={
                "active_cell_id": {"type": "string", "description": "Active cell ID"},
                "radius": {"type": "integer", "description": "Expansion radius"},
                "query": {"type": "string", "description": "Search query string"},
                "globs": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Optional glob patterns",
                    "optional": True,
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max results (default 20)",
                    "optional": True,
                },
            },
            fn=_repo_search,
        ))

        self._register(ToolDef(
            name="repo.stage_patch",
            description=(
                "Stage a unified diff patch for a task. "
                "Computes SHA256 and tracks touched files."
            ),
            parameters={
                "task_id": {"type": "string", "description": "Task ID"},
                "patch_unified_diff": {"type": "string", "description": "Unified diff content"},
            },
            fn=lambda task_id, patch_unified_diff: stage_patch(
                base, task_id, patch_unified_diff
            ),
        ))

        self._register(ToolDef(
            name="repo.commit_patch",
            description="Commit a staged patch after all checks pass.",
            parameters={"task_id": {"type": "string", "description": "Task ID"}},
            fn=lambda task_id: commit_patch(base, task_id),
        ))

        self._register(ToolDef(
            name="repo.approve_patch",
            description="Approve a staged patch that requires human approval.",
            parameters={
                "task_id": {"type": "string", "description": "Task ID"},
                "approver": {"type": "string", "description": "Approver identifier"},
                "reason": {"type": "string", "description": "Approval reason"},
            },
            fn=lambda task_id, approver, reason: approve_patch(
                base, task_id, approver, reason
            ),
        ))

        self._register(ToolDef(
            name="repo.abort_patch",
            description="Abort a staged patch and clean up.",
            parameters={"task_id": {"type": "string", "description": "Task ID"}},
            fn=lambda task_id: abort_patch(base, task_id),
        ))

        self._register(ToolDef(
            name="repo.diff",
            description="Show the unified diff of a staged patch.",
            parameters={"task_id": {"type": "string", "description": "Task ID"}},
            fn=lambda task_id: {"diff": diff_task(base, task_id)},
        ))

        self._register(ToolDef(
            name="repo.files_touched",
            description="List files touched by a staged patch.",
            parameters={"task_id": {"type": "string", "description": "Task ID"}},
            fn=lambda task_id: {"files": files_touched(base, task_id)},
        ))

        def _proof_collect(
            task_id: str, obligations: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            policy = load_policy(base)
            task = load_task(base, task_id)
            if obligations is not None:
                task.port_check["obligations"] = obligations
            proofs = collect_task_proofs(base, policy, task.to_dict())
            task.proofs = proofs
            save_task(base, task)
            return proofs

        self._register(ToolDef(
            name="proof.collect",
            description="Run required proof checks and collect artifacts.",
            parameters={
                "task_id": {"type": "string", "description": "Task ID"},
                "obligations": {
                    "type": "object", "description": "Override obligations", "optional": True,
                },
            },
            fn=_proof_collect,
        ))

        def _proof_verify(task_id: str) -> dict[str, Any]:
            task = load_task(base, task_id)
            verification = verify_task_proofs(base, task.to_dict())
            task.proofs["verification"] = verification
            save_task(base, task)
            return verification

        self._register(ToolDef(
            name="proof.verify",
            description="Verify proof artifacts for a staged task.",
            parameters={"task_id": {"type": "string", "description": "Task ID"}},
            fn=_proof_verify,
        ))

        def _proof_attach(task_id: str, artifact_refs: list[str]) -> dict[str, Any]:
            task = load_task(base, task_id)
            task.proofs.setdefault("artifacts", []).extend(artifact_refs)
            save_task(base, task)
            if task.audit_run_id:
                attach_artifacts(base, task.audit_run_id, artifact_refs)
            return {"attached": artifact_refs}

        self._register(ToolDef(
            name="proof.attach",
            description="Attach external artifacts to a task's proof set.",
            parameters={
                "task_id": {"type": "string", "description": "Task ID"},
                "artifact_refs": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Artifact reference paths",
                },
            },
            fn=_proof_attach,
        ))

        def _cmd_run(
            active_cell_id: str,
            radius: int,
            command: str,
            cwd: str | None = None,
            timeout_s: int | None = None,
        ) -> dict[str, Any]:
            policy = load_policy(base)
            hexmap = load_hexmap(base)
            effective_cwd = cwd or self._default_cwd(active_cell_id)
            if effective_cwd:
                authorize_path(
                    base, hexmap, policy, active_cell_id, radius,
                    effective_cwd.rstrip("/") + "/dummy",
                )
            run = start_run(
                base, "cmd.run",
                active_cell_id=active_cell_id, radius=radius,
                allowed=calc_allowed_cells(hexmap, active_cell_id, radius),
            )
            append_event(
                base, run.run_id, "cmd.run",
                {"command": command, "cwd": effective_cwd, "timeout_s": timeout_s},
            )
            result = run_allowed_command(
                base, policy, command, cwd=effective_cwd, timeout_s=timeout_s,
            )
            status = "ok" if result["returncode"] == 0 else "failed"
            update_run(base, run.run_id, status=status)
            finish_run(base, run.run_id, status)
            return result

        self._register(ToolDef(
            name="cmd.run",
            description="Run an allowed command within the authorized scope.",
            parameters={
                "active_cell_id": {"type": "string", "description": "Active cell ID"},
                "radius": {"type": "integer", "description": "Expansion radius"},
                "command": {"type": "string", "description": "Command to execute"},
                "cwd": {
                    "type": "string", "description": "Working directory override", "optional": True,
                },
                "timeout_s": {
                    "type": "integer", "description": "Timeout in seconds", "optional": True,
                },
            },
            fn=_cmd_run,
        ))

        def _tests_run(
            active_cell_id: str, radius: int, scope: str = "cell",
        ) -> dict[str, Any]:
            hexmap = load_hexmap(base)
            policy = load_policy(base)
            allowed = calc_allowed_cells(hexmap, active_cell_id, radius)
            selected = [active_cell_id] if scope == "cell" else allowed
            outputs = []
            for cell_id in selected:
                cell = hexmap.cell(cell_id)
                for test in cell.tests:
                    outputs.append(run_allowed_command(base, policy, test))
            return {"scope": scope, "cells": selected, "output": outputs}

        self._register(ToolDef(
            name="tests.run",
            description="Run tests for the active cell or all allowed cells.",
            parameters={
                "active_cell_id": {"type": "string", "description": "Active cell ID"},
                "radius": {"type": "integer", "description": "Expansion radius"},
                "scope": {
                    "type": "string", "description": "'cell' or 'radius'", "optional": True,
                },
            },
            fn=_tests_run,
        ))

        def _metrics_compute(task_id: str) -> dict[str, Any]:
            task = load_task(base, task_id)
            metrics = compute_metrics(base, task.to_dict())
            task.metrics = metrics
            save_task(base, task)
            if task.audit_run_id:
                update_run(base, task.audit_run_id, metrics=metrics)
            return metrics

        self._register(ToolDef(
            name="metrics.compute",
            description="Compute metrics for a staged task.",
            parameters={"task_id": {"type": "string", "description": "Task ID"}},
            fn=_metrics_compute,
        ))

        self._register(ToolDef(
            name="metrics.report",
            description="Generate a markdown metrics report for an audit run.",
            parameters={"run_id": {"type": "string", "description": "Audit run ID"}},
            fn=lambda run_id: {"markdown": report_markdown(base, run_id)},
        ))

        self._register(ToolDef(
            name="metrics.parent_report",
            description="Generate a markdown metrics report for a parent group.",
            parameters={"parent_id": {"type": "string", "description": "Parent group ID"}},
            fn=lambda parent_id: {"markdown": parent_report(base, parent_id)},
        ))

        self._register(ToolDef(
            name="risk.top_ports",
            description="List the top N riskiest ports by policy risk score.",
            parameters={
                "n": {
                    "type": "integer",
                    "description": "Number of ports to return",
                    "optional": True,
                },
            },
            fn=lambda n=10: {"ports": top_risky_ports(base, n)},
        ))
