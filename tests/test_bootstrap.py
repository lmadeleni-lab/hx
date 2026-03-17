from __future__ import annotations

import subprocess
from pathlib import Path

from hx.bootstrap import (
    generate_agents_update,
    generate_claude_md,
    generate_governance_rules,
    generate_memory_index,
    generate_project_context,
    run_bootstrap,
)
from hx.cli import main
from hx.hexmap import load_hexmap
from hx.policy import load_policy
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


def test_bootstrap_creates_claude_dir(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    result = run_bootstrap(tmp_path)
    assert ".claude/CLAUDE.md" in result["files_written"]
    assert (tmp_path / ".claude" / "CLAUDE.md").exists()


def test_bootstrap_creates_memory_files(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    result = run_bootstrap(tmp_path)
    assert ".claude/memory/MEMORY.md" in result["files_written"]
    assert ".claude/memory/project-context.md" in result["files_written"]
    assert ".claude/memory/governance-rules.md" in result["files_written"]
    assert (tmp_path / ".claude" / "memory" / "MEMORY.md").exists()
    assert (tmp_path / ".claude" / "memory" / "project-context.md").exists()
    assert (tmp_path / ".claude" / "memory" / "governance-rules.md").exists()


def test_bootstrap_updates_agents_md(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    run_bootstrap(tmp_path)
    content = (tmp_path / "AGENTS.md").read_text()
    assert "Bootstrap Context" in content


def test_bootstrap_reflects_hexmap_cells(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    run_bootstrap(tmp_path)
    claude_md = (tmp_path / ".claude" / "CLAUDE.md").read_text()
    hexmap = load_hexmap(tmp_path)
    for cell in hexmap.cells:
        assert cell.cell_id in claude_md


def test_bootstrap_reflects_policy_mode(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    run_bootstrap(tmp_path)
    rules = (tmp_path / ".claude" / "memory" / "governance-rules.md").read_text()
    assert "dev" in rules


def test_bootstrap_requires_init_first(tmp_path: Path) -> None:
    _git_init(tmp_path)
    result = run_bootstrap(tmp_path)
    assert result.get("error")
    assert result["files_written"] == []


def test_bootstrap_force_overwrites(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    run_bootstrap(tmp_path)
    (tmp_path / ".claude" / "CLAUDE.md").write_text("custom\n")
    run_bootstrap(tmp_path, force=True)
    assert "custom" not in (tmp_path / ".claude" / "CLAUDE.md").read_text()


def test_bootstrap_cli(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    rc = main(["--root", str(tmp_path), "--ui-mode", "quiet", "bootstrap"])
    assert rc == 0
    assert (tmp_path / ".claude" / "CLAUDE.md").exists()


def test_generate_claude_md_content(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    hexmap = load_hexmap(tmp_path)
    policy = load_policy(tmp_path)
    md = generate_claude_md(hexmap, policy)
    assert "hx" in md
    assert "Governance Mode" in md
    assert "Cell Map" in md


def test_generate_memory_index() -> None:
    index = generate_memory_index()
    assert "project-context.md" in index
    assert "governance-rules.md" in index


def test_generate_project_context(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    hexmap = load_hexmap(tmp_path)
    policy = load_policy(tmp_path)
    ctx = generate_project_context(hexmap, policy, "python")
    assert "python" in ctx
    assert "dev" in ctx


def test_generate_governance_rules(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    policy = load_policy(tmp_path)
    rules = generate_governance_rules(policy)
    assert "Approval Gates" in rules
    assert "Risk Weights" in rules


def test_generate_agents_update(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    hexmap = load_hexmap(tmp_path)
    policy = load_policy(tmp_path)
    update = generate_agents_update(hexmap, policy)
    assert "Bootstrap Context" in update
    assert "Governance mode" in update
