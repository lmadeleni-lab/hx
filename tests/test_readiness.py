from __future__ import annotations

import subprocess
from pathlib import Path

from hx.cli import main
from hx.readiness import check_readiness, render_readiness
from hx.setup import run_setup


def _git_init(tmp_path: Path) -> None:
    subprocess.run(
        ["git", "init"], cwd=tmp_path, check=True, capture_output=True,
    )


def _init_repo(tmp_path: Path) -> None:
    _git_init(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hi')\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("def test(): pass\n")
    run_setup(tmp_path)


def test_readiness_returns_all_checks(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    report = check_readiness(tmp_path)
    assert "passed" in report
    assert "total" in report
    assert "checks" in report
    assert "recommendations" in report
    assert len(report["checks"]) >= 6


def test_readiness_scaffold_check(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    report = check_readiness(tmp_path)
    scaffold = next(c for c in report["checks"] if c["name"] == "scaffold")
    assert scaffold["ok"] is True


def test_readiness_hexmap_check(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    report = check_readiness(tmp_path)
    hexmap = next(c for c in report["checks"] if c["name"] == "hexmap")
    assert hexmap["ok"] is True
    assert hexmap["detail"]["cells"] >= 1


def test_readiness_git_check(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    report = check_readiness(tmp_path)
    git = next(c for c in report["checks"] if c["name"] == "git")
    assert git["ok"] is True


def test_readiness_test_check(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    report = check_readiness(tmp_path)
    tests = next(c for c in report["checks"] if c["name"] == "tests")
    assert tests["ok"] is True
    assert tests["detail"]["test_files"] >= 1


def test_readiness_no_tests_recommends(tmp_path: Path) -> None:
    _git_init(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("x = 1\n")
    run_setup(tmp_path)
    report = check_readiness(tmp_path)
    tests = next(c for c in report["checks"] if c["name"] == "tests")
    assert tests["ok"] is False


def test_readiness_uninit_recommends_setup(tmp_path: Path) -> None:
    _git_init(tmp_path)
    report = check_readiness(tmp_path)
    assert any("hx setup" in r for r in report["recommendations"])


def test_readiness_recommends_bootstrap(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    report = check_readiness(tmp_path)
    assert any("hx bootstrap" in r for r in report["recommendations"])


def test_readiness_cli(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    rc = main(["--root", str(tmp_path), "--ui-mode", "quiet", "readiness"])
    # May return 1 if not fully ready (e.g., no bootstrap), that's fine
    assert rc in (0, 1)


def test_readiness_cli_json(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    rc = main([
        "--root", str(tmp_path), "--ui-mode", "quiet",
        "readiness", "--json",
    ])
    assert rc in (0, 1)


def test_render_readiness(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    report = check_readiness(tmp_path)
    rendered = render_readiness(report, color=False)
    assert "hx readiness" in rendered
    assert "checks passed" in rendered


def test_render_readiness_with_color(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    report = check_readiness(tmp_path)
    rendered = render_readiness(report, color=True)
    assert "hx readiness" in rendered
