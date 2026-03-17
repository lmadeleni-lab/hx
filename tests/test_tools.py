"""Tests for the ToolRegistry."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from hx.templates import policy_toml, starter_hexmap
from hx.tools import ToolRegistry


@pytest.fixture()
def hx_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "HEXMAP.json").write_text(starter_hexmap())
    (tmp_path / "POLICY.toml").write_text(policy_toml())
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "demo.py").write_text('print("hello")\n')
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_demo.py").write_text("def test_pass(): pass\n")
    return tmp_path


class TestToolRegistryBasics:
    def test_all_returns_tools(self, hx_repo: Path) -> None:
        registry = ToolRegistry(hx_repo)
        tools = registry.all()
        assert len(tools) > 20
        names = {t.name for t in tools}
        assert "hex.resolve_cell" in names
        assert "repo.read" in names
        assert "port.check" in names

    def test_call_hex_resolve_cell(self, hx_repo: Path) -> None:
        registry = ToolRegistry(hx_repo)
        result = registry.call("hex.resolve_cell", {"path": "src/demo.py"})
        assert "cell_id" in result

    def test_call_hex_allowed_cells(self, hx_repo: Path) -> None:
        registry = ToolRegistry(hx_repo)
        result = registry.call("hex.allowed_cells", {"active_cell_id": "root", "radius": 0})
        assert "cells" in result
        assert "root" in result["cells"]

    def test_call_unknown_tool_raises(self, hx_repo: Path) -> None:
        registry = ToolRegistry(hx_repo)
        with pytest.raises(KeyError, match="Unknown tool"):
            registry.call("nonexistent.tool", {})

    def test_get_returns_none_for_unknown(self, hx_repo: Path) -> None:
        registry = ToolRegistry(hx_repo)
        assert registry.get("nonexistent") is None
        assert registry.get("hex.resolve_cell") is not None


class TestAnthropicSchemas:
    def test_schemas_have_correct_format(self, hx_repo: Path) -> None:
        registry = ToolRegistry(hx_repo)
        schemas = registry.anthropic_tool_schemas()
        assert len(schemas) > 0
        for schema in schemas:
            assert "name" in schema
            assert "description" in schema
            assert "input_schema" in schema
            assert schema["input_schema"]["type"] == "object"
            # No dots in API names
            assert "." not in schema["name"]

    def test_resolve_api_name(self, hx_repo: Path) -> None:
        registry = ToolRegistry(hx_repo)
        assert registry.resolve_api_name("hex_resolve_cell") == "hex.resolve_cell"
        assert registry.resolve_api_name("repo_read") == "repo.read"
        assert registry.resolve_api_name("port_check") == "port.check"

    def test_resolve_unknown_api_name_raises(self, hx_repo: Path) -> None:
        registry = ToolRegistry(hx_repo)
        with pytest.raises(KeyError):
            registry.resolve_api_name("totally_fake_xyz")
