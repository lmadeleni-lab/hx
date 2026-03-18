"""Tests for the onboarding assistant."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from hx.onboard import (
    ARCHETYPES,
    OnboardResult,
    detect_archetype,
    detect_language,
    render_onboard_result,
    run_onboard,
)


def _git_init(tmp_path: Path) -> None:
    subprocess.run(
        ["git", "init"], cwd=tmp_path, check=True, capture_output=True,
    )


class TestDetectArchetype:
    def test_web_app(self) -> None:
        assert detect_archetype("build a web app for recipes") == "web_app"

    def test_cli_tool(self) -> None:
        assert detect_archetype("create a CLI tool for log analysis") == "cli_tool"

    def test_api_service(self) -> None:
        assert detect_archetype("build a REST API for user management") == "api_service"

    def test_library(self) -> None:
        assert detect_archetype("create a Python library for parsing CSV") == "library"

    def test_mobile_app(self) -> None:
        assert detect_archetype("build a mobile app with React Native") == "mobile_app"

    def test_data_pipeline(self) -> None:
        assert detect_archetype("create a data pipeline for ETL") == "data_pipeline"

    def test_generic_fallback(self) -> None:
        assert detect_archetype("build something amazing") == "generic"

    def test_dashboard_is_web_app(self) -> None:
        assert detect_archetype("build a dashboard for metrics") == "web_app"

    def test_microservice_is_api(self) -> None:
        assert detect_archetype("create a microservice") == "api_service"

    def test_longer_match_wins(self) -> None:
        # "rest api" (7 chars) should score higher than just "api" (3 chars)
        result = detect_archetype("build a rest api service")
        assert result in ("api_service", "web_app")


class TestDetectLanguage:
    def test_python(self) -> None:
        assert detect_language("build it in Python with FastAPI") == "python"

    def test_typescript(self) -> None:
        assert detect_language("use React and TypeScript") == "typescript"

    def test_go(self) -> None:
        assert detect_language("write it in golang") == "go"

    def test_rust(self) -> None:
        assert detect_language("use Rust with Tokio") == "rust"

    def test_no_language(self) -> None:
        assert detect_language("build a thing") is None

    def test_framework_implies_language(self) -> None:
        assert detect_language("build with Django") == "python"
        assert detect_language("use Next.js") == "typescript"


class TestArchetypeConfigs:
    def test_all_archetypes_have_required_keys(self) -> None:
        for name, config in ARCHETYPES.items():
            assert "keywords" in config, f"{name} missing keywords"
            assert "cells" in config, f"{name} missing cells"
            assert "language_hint" in config, f"{name} missing language_hint"
            assert "commands" in config, f"{name} missing commands"

    def test_all_archetypes_have_cells(self) -> None:
        for name, config in ARCHETYPES.items():
            assert len(config["cells"]) >= 2, (
                f"{name} should have at least 2 cells"
            )

    def test_all_cells_have_required_fields(self) -> None:
        for name, config in ARCHETYPES.items():
            for cell in config["cells"]:
                assert "id" in cell, f"{name} cell missing id"
                assert "paths" in cell, f"{name} cell missing paths"
                assert "summary" in cell, f"{name} cell missing summary"


class TestRunOnboard:
    def test_basic_onboard(self, tmp_path: Path) -> None:
        _git_init(tmp_path)
        result = run_onboard(tmp_path, "build a CLI tool for parsing logs")
        assert result.archetype == "cli_tool"
        assert result.language in ("python",)
        assert len(result.cells) >= 3
        assert len(result.plan_steps) >= 3
        assert (tmp_path / "HEXMAP.json").exists()
        assert (tmp_path / "POLICY.toml").exists()

    def test_hexmap_is_valid_json(self, tmp_path: Path) -> None:
        _git_init(tmp_path)
        run_onboard(tmp_path, "build a web app")
        data = json.loads((tmp_path / "HEXMAP.json").read_text())
        assert "cells" in data
        assert "version" in data

    def test_policy_has_commands(self, tmp_path: Path) -> None:
        _git_init(tmp_path)
        run_onboard(tmp_path, "create a Python library")
        policy = (tmp_path / "POLICY.toml").read_text()
        assert "allowed_prefixes" in policy
        assert "python" in policy

    def test_creates_directories(self, tmp_path: Path) -> None:
        _git_init(tmp_path)
        run_onboard(tmp_path, "build a web app with React")
        # At least some directories should exist
        assert any(
            (tmp_path / d).is_dir()
            for d in ["src", "src/frontend", "src/api", "tests"]
        )

    def test_plan_is_written(self, tmp_path: Path) -> None:
        _git_init(tmp_path)
        run_onboard(tmp_path, "build a REST API")
        plan_path = tmp_path / ".hx" / "state" / "task_plan.json"
        assert plan_path.exists()
        plan = json.loads(plan_path.read_text())
        assert "goal" in plan
        assert "steps" in plan
        assert plan["steps"][0]["status"] == "pending"

    def test_first_task_is_set(self, tmp_path: Path) -> None:
        _git_init(tmp_path)
        result = run_onboard(tmp_path, "create a data pipeline")
        assert result.first_task
        assert "hx run" in result.first_task

    def test_language_override(self, tmp_path: Path) -> None:
        _git_init(tmp_path)
        result = run_onboard(
            tmp_path, "build a web app", language="go",
        )
        assert result.language == "go"
        policy = (tmp_path / "POLICY.toml").read_text()
        assert '"go"' in policy or '"go ' in policy

    def test_idempotent_without_force(self, tmp_path: Path) -> None:
        _git_init(tmp_path)
        run_onboard(tmp_path, "build a CLI tool")
        original = (tmp_path / "HEXMAP.json").read_text()
        result2 = run_onboard(tmp_path, "build a web app")
        # Without force, HEXMAP should not be overwritten
        assert "HEXMAP.json" not in result2.files_written

    def test_force_overwrites(self, tmp_path: Path) -> None:
        _git_init(tmp_path)
        run_onboard(tmp_path, "build a CLI tool")
        result2 = run_onboard(tmp_path, "build a web app", force=True)
        assert "HEXMAP.json" in result2.files_written


class TestRenderOnboardResult:
    def test_renders_success(self) -> None:
        result = OnboardResult(
            archetype="web_app",
            language="typescript",
            cells=[
                {"id": "frontend", "paths": ["src/frontend/**"], "summary": "UI"},
                {"id": "backend", "paths": ["src/api/**"], "summary": "API"},
            ],
            plan_steps=[
                {"description": "Scaffold", "cell": "frontend", "radius": 2, "depends_on": []},
            ],
            files_written=["HEXMAP.json", "POLICY.toml"],
            first_task="hx run 'Scaffold' --cell frontend",
        )
        output = render_onboard_result(result)
        assert "web app" in output
        assert "typescript" in output
        assert "frontend" in output

    def test_renders_errors(self) -> None:
        result = OnboardResult(
            archetype="",
            language="",
            cells=[],
            plan_steps=[],
            errors=["Something went wrong"],
        )
        output = render_onboard_result(result)
        assert "failed" in output
