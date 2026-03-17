from __future__ import annotations

import subprocess
from pathlib import Path

from hx.cli import main
from hx.hexmap import load_hexmap
from hx.setup import (
    detect_primary_language,
    hexmap_stats,
    run_setup,
    suggest_policy_mode,
)


def _git_init(tmp_path: Path) -> None:
    subprocess.run(
        ["git", "init"], cwd=tmp_path, check=True, capture_output=True,
    )


def _populate_python(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hello')\n")
    (tmp_path / "src" / "utils.py").write_text("x = 1\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("def test_a(): pass\n")


def test_detect_python(tmp_path: Path) -> None:
    _populate_python(tmp_path)
    assert detect_primary_language(tmp_path) == "python"


def test_detect_typescript(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "index.ts").write_text("export {}")
    (tmp_path / "src" / "app.tsx").write_text("export {}")
    assert detect_primary_language(tmp_path) == "typescript"


def test_detect_unknown_empty(tmp_path: Path) -> None:
    assert detect_primary_language(tmp_path) == "unknown"


def test_suggest_dev_for_small_repo(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _populate_python(tmp_path)
    run_setup(tmp_path)
    hexmap = load_hexmap(tmp_path)
    assert suggest_policy_mode(tmp_path, hexmap) == "dev"


def test_setup_runs_full_flow(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _populate_python(tmp_path)
    result = run_setup(tmp_path)

    assert result["language"] == "python"
    assert result["stats"]["cells"] >= 1
    assert (tmp_path / "AGENTS.md").exists()
    assert (tmp_path / "TOOLS.md").exists()
    assert (tmp_path / "POLICY.toml").exists()
    assert (tmp_path / "HEXMAP.json").exists()
    assert (tmp_path / ".hx").is_dir()


def test_setup_cli(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _populate_python(tmp_path)
    rc = main(["--root", str(tmp_path), "--ui-mode", "quiet", "setup"])
    assert rc == 0
    assert (tmp_path / "HEXMAP.json").exists()


def test_setup_is_idempotent(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _populate_python(tmp_path)
    run_setup(tmp_path)
    agents_content = (tmp_path / "AGENTS.md").read_text()
    # Second run without force should not overwrite
    result2 = run_setup(tmp_path)
    assert (tmp_path / "AGENTS.md").read_text() == agents_content
    # HEXMAP.json is always rewritten by build_hexmap
    assert "HEXMAP.json" in result2["files_written"]


def test_setup_force_overwrites(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _populate_python(tmp_path)
    run_setup(tmp_path)
    (tmp_path / "AGENTS.md").write_text("custom content\n")
    run_setup(tmp_path, force=True)
    assert "custom content" not in (tmp_path / "AGENTS.md").read_text()


def test_hexmap_stats_counts(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _populate_python(tmp_path)
    run_setup(tmp_path)
    hexmap = load_hexmap(tmp_path)
    stats = hexmap_stats(hexmap)
    assert stats["cells"] >= 1
    assert isinstance(stats["ports"], int)
    assert isinstance(stats["boundary_crossings"], int)
