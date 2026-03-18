from __future__ import annotations

import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from hx import __version__
from hx.config import repo_root
from hx.hexmap import load_hexmap
from hx.parents import parent_groups_overview, parent_summary
from hx.tools import ToolRegistry


def create_server(root: Path | None = None) -> FastMCP:
    return create_server_with_options(root)


def create_server_with_options(
    root: Path | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> FastMCP:
    base = repo_root(root)
    registry = ToolRegistry(base)
    mcp = FastMCP(
        name="hx",
        instructions=f"hx {__version__}",
        host=host,
        port=port,
    )

    # Register all tools from the registry onto the MCP server
    for tool_def in registry.all():
        mcp.tool(name=tool_def.name)(tool_def.fn)

    # Resources (not tools — these stay in mcp_server.py)
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
        resolved = (base / path).resolve()
        if not resolved.is_relative_to(base.resolve()):
            raise PermissionError(f"Path traversal blocked: {path}")
        return resolved.read_text()

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

    # Prompts
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
