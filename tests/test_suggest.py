from __future__ import annotations

import subprocess
from pathlib import Path

from hx.cli import main
from hx.setup import run_setup
from hx.suggest import suggest_tasks


def _git_init(tmp_path: Path) -> None:
    subprocess.run(
        ["git", "init"], cwd=tmp_path, check=True, capture_output=True,
    )


def _init_repo(tmp_path: Path, *, with_tests: bool = True) -> None:
    _git_init(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hi')\n")
    if with_tests:
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_app.py").write_text("def test(): pass\n")
    run_setup(tmp_path)


def test_suggest_without_init(tmp_path: Path) -> None:
    _git_init(tmp_path)
    suggestions = suggest_tasks(tmp_path)
    assert len(suggestions) >= 1
    assert suggestions[0]["command"] == "hx setup"


def test_suggest_returns_tasks(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    suggestions = suggest_tasks(tmp_path)
    assert isinstance(suggestions, list)
    for s in suggestions:
        assert "task" in s
        assert "command" in s
        assert "risk" in s
        assert "reason" in s


def test_suggest_sorted_by_risk(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    suggestions = suggest_tasks(tmp_path)
    risk_order = {"none": 0, "low": 1, "medium": 2, "high": 3}
    risks = [risk_order.get(s["risk"], 99) for s in suggestions]
    assert risks == sorted(risks)


def test_suggest_missing_tests(tmp_path: Path) -> None:
    _init_repo(tmp_path, with_tests=False)
    suggestions = suggest_tasks(tmp_path)
    test_tasks = [s for s in suggestions if "test" in s["task"].lower()]
    assert len(test_tasks) >= 1


def test_suggest_missing_bootstrap(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    suggestions = suggest_tasks(tmp_path)
    bootstrap = [s for s in suggestions if "bootstrap" in s["command"].lower()]
    assert len(bootstrap) >= 1


def test_suggest_auto_discovered_cells(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    suggestions = suggest_tasks(tmp_path)
    doc_tasks = [s for s in suggestions if "document" in s["task"].lower()]
    # Cells with auto-discovered summaries should get doc suggestions
    assert len(doc_tasks) >= 1


def test_suggest_cli(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    rc = main(["--root", str(tmp_path), "--ui-mode", "quiet", "suggest"])
    assert rc == 0


def test_suggest_cli_json(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    rc = main([
        "--root", str(tmp_path), "--ui-mode", "quiet",
        "suggest", "--json",
    ])
    assert rc == 0


def test_suggest_cli_limit(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    rc = main([
        "--root", str(tmp_path), "--ui-mode", "quiet",
        "suggest", "-n", "2",
    ])
    assert rc == 0
