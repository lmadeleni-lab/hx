from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from hx import __version__
from hx.audit import append_event, finish_run, start_run, update_run
from hx.authz import allowed_cells as calc_allowed_cells
from hx.authz import authorize_path
from hx.config import ensure_hx_dirs, repo_root
from hx.hexmap import load_hexmap, resolve_cell_id
from hx.metrics import compute_metrics, parent_report, report_markdown, top_risky_ports
from hx.parents import (
    parent_group_context,
    parent_groups_overview,
    parent_summary,
    resolve_parent_group,
)
from hx.policy import default_radius, load_policy
from hx.ports import check_task_ports, describe_port, port_surface, surface_diff
from hx.proof import (
    attach_artifacts,
    collect_task_proofs,
    run_allowed_command,
    verify_task_proofs,
)
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


def create_server(root: Path | None = None) -> FastMCP:
    return create_server_with_options(root)


def create_server_with_options(
    root: Path | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> FastMCP:
    base = repo_root(root)
    ensure_hx_dirs(base)
    mcp = FastMCP(
        name="hx",
        instructions=f"hx {__version__}",
        host=host,
        port=port,
    )

    def default_cwd(active_cell_id: str) -> str | None:
        hexmap = load_hexmap(base)
        cell = hexmap.cell(active_cell_id)
        for pattern in cell.paths:
            for path in base.glob(pattern):
                if path.is_dir():
                    return str(path.relative_to(base))
                return str(path.parent.relative_to(base))
        return None

    @mcp.tool(name="hex.resolve_cell")
    def hex_resolve_cell(path: str) -> dict[str, Any]:
        hexmap = load_hexmap(base)
        return {"cell_id": resolve_cell_id(hexmap, path)}

    @mcp.tool(name="hex.allowed_cells")
    def hex_allowed_cells(active_cell_id: str, radius: int) -> dict[str, Any]:
        hexmap = load_hexmap(base)
        return {"cells": calc_allowed_cells(hexmap, active_cell_id, radius)}

    @mcp.tool(name="hex.context")
    def hex_context(active_cell_id: str, radius: int) -> dict[str, Any]:
        hexmap = load_hexmap(base)
        allowed = calc_allowed_cells(hexmap, active_cell_id, radius)
        files = []
        summaries = []
        ports = []
        for cell_id in allowed:
            cell = hexmap.cell(cell_id)
            summaries.append(
                {
                    "cell_id": cell.cell_id,
                    "summary": cell.summary,
                    "invariants": cell.invariants,
                }
            )
            for pattern in cell.paths:
                files.extend(
                    str(path.relative_to(base))
                    for path in base.glob(pattern)
                    if path.is_file()
                )
            for index in range(6):
                ports.append(describe_port(hexmap, cell_id, index))
        return {"files": sorted(set(files)), "summaries": summaries, "ports": ports}

    @mcp.tool(name="hex.neighbors")
    def hex_neighbors(cell_id: str) -> dict[str, Any]:
        hexmap = load_hexmap(base)
        cell = hexmap.cell(cell_id)
        return {
            "ports": [
                {"side_index": index, "neighbor_cell_id": neighbor}
                for index, neighbor in enumerate(cell.neighbors)
            ]
        }

    @mcp.tool(name="hex.radius_expand_request")
    def hex_radius_expand_request(
        active_cell_id: str,
        from_radius: int,
        to_radius: int,
        justification: str,
    ) -> dict[str, Any]:
        _ = active_cell_id, from_radius
        policy = load_policy(base)
        approved = to_radius <= default_radius(policy) and bool(justification.strip())
        reason = (
            "auto-approved"
            if approved
            else "policy threshold exceeded or missing justification"
        )
        return {"approved": approved, "reason": reason}

    @mcp.tool(name="hex.parent_groups")
    def hex_parent_groups() -> dict[str, Any]:
        hexmap = load_hexmap(base)
        return {"parents": parent_groups_overview(base, hexmap)}

    @mcp.tool(name="hex.parent_resolve")
    def hex_parent_resolve(cell_id: str) -> dict[str, Any]:
        hexmap = load_hexmap(base)
        resolved = resolve_parent_group(hexmap, cell_id)
        if resolved is None:
            raise KeyError(f"No parent group found for cell {cell_id}")
        return resolved

    @mcp.tool(name="hex.parent_neighbors")
    def hex_parent_neighbors(parent_id: str) -> dict[str, Any]:
        hexmap = load_hexmap(base)
        return {"neighbors": parent_summary(base, hexmap, parent_id)["derived_neighbors"]}

    @mcp.tool(name="hex.parent_context")
    def hex_parent_context(parent_id: str) -> dict[str, Any]:
        hexmap = load_hexmap(base)
        context = parent_group_context(hexmap, parent_id)
        summary = parent_summary(base, hexmap, parent_id)
        return {
            "cells": context["cells"],
            "summaries": summary["child_summaries"],
            "boundary_ports": summary["boundary_ports"],
            "risks": summary["risky_ports"],
        }

    @mcp.tool(name="hex.parent_summary")
    def hex_parent_summary(parent_id: str) -> dict[str, Any]:
        hexmap = load_hexmap(base)
        return parent_summary(base, hexmap, parent_id)

    @mcp.tool(name="port.describe")
    def tool_port_describe(cell_id: str, side_index: int) -> dict[str, Any]:
        return describe_port(load_hexmap(base), cell_id, side_index)

    @mcp.tool(name="port.surface")
    def tool_port_surface(cell_id: str, side_index: int) -> dict[str, Any]:
        return port_surface(base, load_hexmap(base), cell_id, side_index)

    @mcp.tool(name="port.surface_diff")
    def tool_port_surface_diff(task_id: str) -> dict[str, Any]:
        task = load_task(base, task_id).to_dict()
        return surface_diff(base, task)

    @mcp.tool(name="port.check")
    def tool_port_check(task_id: str, active_cell_id: str, radius: int) -> dict[str, Any]:
        task = load_task(base, task_id)
        task.active_cell_id = active_cell_id
        task.radius = radius
        task.port_check = check_task_ports(base, task.to_dict(), active_cell_id, radius)
        save_task(base, task)
        return task.port_check

    @mcp.tool(name="repo.read")
    def tool_repo_read(active_cell_id: str, radius: int, path: str) -> dict[str, Any]:
        hexmap = load_hexmap(base)
        policy = load_policy(base)
        authorize_path(base, hexmap, policy, active_cell_id, radius, path)
        return {"path": path, "content": repo_read(base, path)}

    @mcp.tool(name="repo.search")
    def tool_repo_search(
        active_cell_id: str,
        radius: int,
        query: str,
        globs: list[str] | None = None,
    ) -> dict[str, Any]:
        hexmap = load_hexmap(base)
        policy = load_policy(base)
        def is_authorized(rel_path: str) -> bool:
            try:
                authorize_path(base, hexmap, policy, active_cell_id, radius, rel_path)
                return True
            except PermissionError:
                return False

        results = repo_search(base, query, globs, path_filter=is_authorized)
        return {"matches": results}

    @mcp.tool(name="repo.stage_patch")
    def tool_repo_stage_patch(task_id: str, patch_unified_diff: str) -> dict[str, Any]:
        return stage_patch(base, task_id, patch_unified_diff)

    @mcp.tool(name="repo.commit_patch")
    def tool_repo_commit_patch(task_id: str) -> dict[str, Any]:
        return commit_patch(base, task_id)

    @mcp.tool(name="repo.approve_patch")
    def tool_repo_approve_patch(
        task_id: str,
        approver: str,
        reason: str,
    ) -> dict[str, Any]:
        return approve_patch(base, task_id, approver, reason)

    @mcp.tool(name="repo.abort_patch")
    def tool_repo_abort_patch(task_id: str) -> dict[str, Any]:
        return abort_patch(base, task_id)

    @mcp.tool(name="repo.diff")
    def tool_repo_diff(task_id: str) -> dict[str, Any]:
        return {"diff": diff_task(base, task_id)}

    @mcp.tool(name="repo.files_touched")
    def tool_repo_files_touched(task_id: str) -> dict[str, Any]:
        return {"files": files_touched(base, task_id)}

    @mcp.tool(name="proof.collect")
    def tool_proof_collect(
        task_id: str,
        obligations: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        policy = load_policy(base)
        task = load_task(base, task_id)
        if obligations is not None:
            task.port_check["obligations"] = obligations
        proofs = collect_task_proofs(base, policy, task.to_dict())
        task.proofs = proofs
        save_task(base, task)
        return proofs

    @mcp.tool(name="proof.verify")
    def tool_proof_verify(task_id: str) -> dict[str, Any]:
        task = load_task(base, task_id)
        verification = verify_task_proofs(base, task.to_dict())
        task.proofs["verification"] = verification
        save_task(base, task)
        return verification

    @mcp.tool(name="proof.attach")
    def tool_proof_attach(task_id: str, artifact_refs: list[str]) -> dict[str, Any]:
        task = load_task(base, task_id)
        task.proofs.setdefault("artifacts", []).extend(artifact_refs)
        save_task(base, task)
        if task.audit_run_id:
            attach_artifacts(base, task.audit_run_id, artifact_refs)
        return {"attached": artifact_refs}

    @mcp.tool(name="cmd.run")
    def tool_cmd_run(
        active_cell_id: str,
        radius: int,
        command: str,
        cwd: str | None = None,
        timeout_s: int | None = None,
    ) -> dict[str, Any]:
        policy = load_policy(base)
        hexmap = load_hexmap(base)
        effective_cwd = cwd or default_cwd(active_cell_id)
        if effective_cwd:
            authorize_path(
                base,
                hexmap,
                policy,
                active_cell_id,
                radius,
                effective_cwd.rstrip("/") + "/dummy",
            )
        run = start_run(
            base,
            "cmd.run",
            active_cell_id=active_cell_id,
            radius=radius,
            allowed=calc_allowed_cells(hexmap, active_cell_id, radius),
        )
        append_event(
            base,
            run.run_id,
            "cmd.run",
            {"command": command, "cwd": effective_cwd, "timeout_s": timeout_s},
        )
        result = run_allowed_command(
            base,
            policy,
            command,
            cwd=effective_cwd,
            timeout_s=timeout_s,
        )
        update_run(base, run.run_id, status="ok" if result["returncode"] == 0 else "failed")
        finish_run(base, run.run_id, "ok" if result["returncode"] == 0 else "failed")
        return result

    @mcp.tool(name="tests.run")
    def tool_tests_run(active_cell_id: str, radius: int, scope: str = "cell") -> dict[str, Any]:
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

    @mcp.tool(name="metrics.compute")
    def tool_metrics_compute(task_id: str) -> dict[str, Any]:
        task = load_task(base, task_id)
        metrics = compute_metrics(base, task.to_dict())
        task.metrics = metrics
        save_task(base, task)
        if task.audit_run_id:
            update_run(base, task.audit_run_id, metrics=metrics)
        return metrics

    @mcp.tool(name="metrics.report")
    def tool_metrics_report(run_id: str) -> dict[str, Any]:
        return {"markdown": report_markdown(base, run_id)}

    @mcp.tool(name="metrics.parent_report")
    def tool_metrics_parent_report(parent_id: str) -> dict[str, Any]:
        return {"markdown": parent_report(base, parent_id)}

    @mcp.tool(name="risk.top_ports")
    def tool_risk_top_ports(n: int = 10) -> dict[str, Any]:
        return {"ports": top_risky_ports(base, n)}

    @mcp.resource("repo://tree")
    def resource_repo_tree() -> str:
        lines = []
        for path in sorted(base.rglob("*")):
            if ".hx" in path.parts:
                continue
            lines.append(str(path.relative_to(base)))
        return "\n".join(lines)

    @mcp.resource("repo://file/{path}")
    def resource_repo_file(path: str) -> str:
        return (base / path).read_text()

    @mcp.resource("hx://hexmap")
    def resource_hexmap() -> str:
        return json.dumps(load_hexmap(base).to_dict(), indent=2)

    @mcp.resource("hx://parent_groups")
    def resource_parent_groups() -> str:
        hexmap = load_hexmap(base)
        return json.dumps(parent_groups_overview(base, hexmap), indent=2)

    @mcp.resource("hx://parent/{parent_id}")
    def resource_parent(parent_id: str) -> str:
        hexmap = load_hexmap(base)
        return json.dumps(parent_summary(base, hexmap, parent_id), indent=2)

    @mcp.resource("hx://policy")
    def resource_policy() -> str:
        return (base / "POLICY.toml").read_text()

    @mcp.resource("hx://audit/{run_id}")
    def resource_audit(run_id: str) -> str:
        from hx.audit import load_run

        return json.dumps(load_run(base, run_id).to_dict(), indent=2)

    @mcp.prompt(name="cell_fix_bug")
    def prompt_cell_fix_bug(active_cell_id: str) -> str:
        return (
            f"Work within cell {active_cell_id} at radius R0 or R1. "
            "Fix the bug with tests before expanding scope."
        )

    @mcp.prompt(name="cell_add_feature_with_tests")
    def prompt_cell_add_feature(active_cell_id: str) -> str:
        return (
            f"Add a feature inside cell {active_cell_id}. Prefer R0. "
            "If ports are impacted, stage the patch and satisfy proof obligations."
        )

    @mcp.prompt(name="port_breaking_change_with_migration")
    def prompt_port_break(active_cell_id: str) -> str:
        return (
            f"Breaking changes from {active_cell_id} require explicit "
            "port analysis, migration notes, and approval."
        )

    @mcp.prompt(name="reduce_boundary_pressure_refactor")
    def prompt_reduce_pressure(active_cell_id: str) -> str:
        return (
            f"Reduce boundary pressure around {active_cell_id} by shrinking "
            "radius needs and simplifying port surfaces."
        )

    @mcp.prompt(name="parent_refine_summary")
    def prompt_parent_refine_summary(parent_id: str) -> str:
        return (
            f"Refine the summary for parent group {parent_id}. "
            "Preserve child-level boundary detail while compressing context."
        )

    @mcp.prompt(name="parent_boundary_review")
    def prompt_parent_boundary_review(parent_id: str) -> str:
        return (
            f"Review parent group {parent_id} for unstable neighboring parents, "
            "risky child ports, and proof hotspots."
        )

    @mcp.prompt(name="parent_reduce_pressure")
    def prompt_parent_reduce_pressure(parent_id: str) -> str:
        return (
            f"Reduce pressure around parent group {parent_id}. "
            "Prefer refactors that improve cohesion without weakening child contracts."
        )

    return mcp


def serve(root: Path | None = None, transport: str = "stdio") -> None:
    server = create_server_with_options(root)
    server.run(transport=transport)
