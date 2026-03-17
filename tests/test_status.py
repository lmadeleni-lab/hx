"""Tests for the status dashboard."""
from __future__ import annotations

import subprocess
from pathlib import Path

from hx.status import gather_status, render_status
from hx.templates import policy_toml, starter_hexmap


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "HEXMAP.json").write_text(starter_hexmap())
    (tmp_path / "POLICY.toml").write_text(policy_toml())
    (tmp_path / ".hx").mkdir(exist_ok=True)
    (tmp_path / ".hx" / "audit").mkdir(exist_ok=True)
    (tmp_path / ".hx" / "tasks").mkdir(exist_ok=True)


class TestGatherStatus:
    def test_returns_expected_keys(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        data = gather_status(tmp_path)
        assert "active_cell_id" in data
        assert "radius" in data
        assert "allowed_cells" in data
        assert "recent_runs" in data
        assert "risky_ports" in data
        assert "total_cells" in data

    def test_active_cell_defaults_to_first(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        data = gather_status(tmp_path)
        assert data["active_cell_id"] == "root"


class TestRenderStatus:
    def test_renders_without_color(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        output = render_status(tmp_path, color=False)
        assert "hx status" in output
        assert "Active cell:" in output
        assert "root" in output

    def test_renders_with_color(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        output = render_status(tmp_path, color=True)
        assert "\033[" in output  # ANSI codes present
        assert "root" in output
