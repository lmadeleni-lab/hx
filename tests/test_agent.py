"""Tests for the agent module (mocked API)."""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from hx.agent import _build_system_prompt, _safe_args
from hx.stream import StreamRenderer, _compact_args, _compact_result
from hx.templates import policy_toml, starter_hexmap
from hx.tools import ToolRegistry


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "HEXMAP.json").write_text(starter_hexmap())
    (tmp_path / "POLICY.toml").write_text(policy_toml())
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "demo.py").write_text('print("hello")\n')


class TestBuildSystemPrompt:
    def test_contains_cell_info(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        registry = ToolRegistry(tmp_path)
        prompt = _build_system_prompt(registry, "root", 1)
        assert "root" in prompt
        assert "Active cell" in prompt
        assert "Governance Rules" in prompt

    def test_contains_radius(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        registry = ToolRegistry(tmp_path)
        prompt = _build_system_prompt(registry, "root", 2)
        assert "R2" in prompt


class TestSafeArgs:
    def test_redacts_long_strings(self) -> None:
        args = {"patch": "x" * 1000, "task_id": "t1"}
        safe = _safe_args(args)
        assert safe["task_id"] == "t1"
        assert "<1000 chars>" in safe["patch"]

    def test_passes_short_strings(self) -> None:
        args = {"task_id": "t1", "path": "src/demo.py"}
        safe = _safe_args(args)
        assert safe == args


class TestStreamRenderer:
    def test_compact_args(self) -> None:
        assert "task_id=t1" in _compact_args({"task_id": "t1"})
        assert "<100 chars>" in _compact_args({"big": "x" * 100})
        assert "3 items" in _compact_args({"files": [1, 2, 3]})

    def test_compact_result_cell(self) -> None:
        assert "my_cell" in _compact_result("hex.resolve_cell", {"cell_id": "my_cell"})

    def test_compact_result_files(self) -> None:
        assert "3 files" in _compact_result("repo.files_touched", {"files": ["a", "b", "c"]})

    def test_compact_result_approval(self) -> None:
        assert "approval required" in _compact_result(
            "port.check", {"requires_approval": True}
        )

    def test_approval_prompt_eof(self) -> None:
        renderer = StreamRenderer(color=False)
        # Simulate EOF on stdin
        with patch("builtins.input", side_effect=EOFError):
            assert renderer.approval_prompt(["breaking change"]) is False
