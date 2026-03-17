from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


def _result_data(result):
    """Extract structured data from a CallToolResult.

    Newer MCP SDK versions return None for structuredContent and put
    JSON in content[0].text instead.
    """
    if result.structuredContent is not None:
        return result.structuredContent
    return json.loads(result.content[0].text)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_mcp_stdio_end_to_end(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "demo.py").write_text('print("hello")\n')

    subprocess.run(
        [sys.executable, "-m", "hx.cli", "--root", str(tmp_path), "init"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [sys.executable, "-m", "hx.cli", "--root", str(tmp_path), "hex", "build"],
        check=True,
        capture_output=True,
    )

    server = StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "hx.cli",
            "--root",
            str(tmp_path),
            "mcp",
            "serve",
            "--transport",
            "stdio",
        ],
        cwd=tmp_path,
    )

    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            init_result = await session.initialize()
            assert init_result.serverInfo.name == "hx"

            tools = await session.list_tools()
            tool_names = {tool.name for tool in tools.tools}
            assert "hex.allowed_cells" in tool_names
            assert "hex.parent_groups" in tool_names
            assert "repo.read" in tool_names

            allowed = await session.call_tool(
                "hex.allowed_cells",
                {"active_cell_id": "src", "radius": 0},
            )
            assert _result_data(allowed) == {"cells": ["src"]}

            repo_read = await session.call_tool(
                "repo.read",
                {
                    "active_cell_id": "src",
                    "radius": 0,
                    "path": "src/demo.py",
                },
            )
            repo_data = _result_data(repo_read)
            assert repo_data["path"] == "src/demo.py"
            assert 'print("hello")' in repo_data["content"]

            parent_groups = await session.call_tool("hex.parent_groups", {})
            assert _result_data(parent_groups)["parents"]

            parent_resource = await session.read_resource("hx://parent_groups")
            assert "parent_id" in parent_resource.contents[0].text

            policy = await session.read_resource("hx://policy")
            assert 'mode = "dev"' in policy.contents[0].text

            prompt = await session.get_prompt("cell_fix_bug", {"active_cell_id": "src"})
            assert "radius R0 or R1" in prompt.messages[0].content.text
