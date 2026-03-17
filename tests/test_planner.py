"""Tests for the task planner and sample prompts."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from hx.cli import main
from hx.planner import (
    SAMPLE_PROMPTS,
    advance_plan,
    create_plan,
    load_plan,
    render_plan,
    render_samples,
)
from hx.setup import run_setup


def _git_init(tmp_path: Path) -> None:
    subprocess.run(
        ["git", "init"], cwd=tmp_path, check=True, capture_output=True,
    )


def _init_repo(tmp_path: Path) -> None:
    _git_init(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("def hello(): pass\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("def test(): pass\n")
    run_setup(tmp_path)


class TestCreatePlan:
    def test_basic_plan(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        plan = create_plan(tmp_path, "Refactor auth", [
            {"description": "Update models", "cell": "src"},
            {"description": "Add tests", "cell": "tests", "depends_on": [0]},
        ])
        assert plan["goal"] == "Refactor auth"
        assert len(plan["steps"]) == 2
        assert plan["steps"][0]["status"] == "pending"
        assert plan["steps"][1]["depends_on"] == [0]

    def test_plan_persists(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        create_plan(tmp_path, "Test", [{"description": "Step 1"}])
        loaded = load_plan(tmp_path)
        assert loaded is not None
        assert loaded["goal"] == "Test"

    def test_invalid_cell_raises(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        with pytest.raises(ValueError, match="unknown cell"):
            create_plan(tmp_path, "Bad", [
                {"description": "Fail", "cell": "nonexistent"},
            ])

    def test_forward_dependency_raises(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        with pytest.raises(ValueError, match="forward dependency"):
            create_plan(tmp_path, "Bad", [
                {"description": "A", "depends_on": [1]},
                {"description": "B"},
            ])

    def test_no_hexmap_still_works(self, tmp_path: Path) -> None:
        _git_init(tmp_path)
        plan = create_plan(tmp_path, "Simple", [
            {"description": "Do thing"},
        ])
        assert len(plan["steps"]) == 1


class TestAdvancePlan:
    def test_advance_marks_completed(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        create_plan(tmp_path, "Test", [
            {"description": "A"},
            {"description": "B", "depends_on": [0]},
        ])
        plan = advance_plan(tmp_path, 0)
        assert plan["steps"][0]["status"] == "completed"
        assert plan["current_step"] == 1

    def test_advance_no_plan_raises(self, tmp_path: Path) -> None:
        _git_init(tmp_path)
        (tmp_path / ".hx" / "state").mkdir(parents=True, exist_ok=True)
        with pytest.raises(RuntimeError, match="No active plan"):
            advance_plan(tmp_path, 0)

    def test_all_done(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        create_plan(tmp_path, "Test", [{"description": "Only step"}])
        plan = advance_plan(tmp_path, 0)
        assert plan["current_step"] == -1


class TestRenderPlan:
    def test_renders(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        plan = create_plan(tmp_path, "My goal", [
            {"description": "Step A", "cell": "src"},
            {"description": "Step B"},
        ])
        text = render_plan(plan)
        assert "My goal" in text
        assert "Step A" in text
        assert "0/2" in text


class TestSamples:
    def test_sample_prompts_not_empty(self) -> None:
        assert len(SAMPLE_PROMPTS) >= 5

    def test_render_samples(self) -> None:
        text = render_samples()
        assert "Bug fix" in text
        assert "hx run" in text
        assert "Tips" in text


class TestCLI:
    def test_samples_command(self, tmp_path: Path) -> None:
        rc = main(["--root", str(tmp_path), "--ui-mode", "quiet", "samples"])
        assert rc == 0

    def test_plan_create_cli(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        rc = main([
            "--root", str(tmp_path), "--ui-mode", "quiet",
            "plan", "create", "My goal",
            "--step", "First step",
            "--step", "Second step",
        ])
        assert rc == 0
        plan = load_plan(tmp_path)
        assert plan is not None
        assert len(plan["steps"]) == 2

    def test_plan_show_cli(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        create_plan(tmp_path, "Goal", [{"description": "A"}])
        rc = main([
            "--root", str(tmp_path), "--ui-mode", "quiet",
            "plan", "show",
        ])
        assert rc == 0

    def test_plan_show_no_plan(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        rc = main([
            "--root", str(tmp_path), "--ui-mode", "quiet",
            "plan", "show",
        ])
        assert rc == 1

    def test_plan_advance_cli(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        create_plan(tmp_path, "Goal", [{"description": "A"}])
        rc = main([
            "--root", str(tmp_path), "--ui-mode", "quiet",
            "plan", "advance", "0",
        ])
        assert rc == 0

    def test_plan_create_no_steps(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        rc = main([
            "--root", str(tmp_path), "--ui-mode", "quiet",
            "plan", "create", "Goal",
        ])
        assert rc == 1
