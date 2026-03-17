"""Tests for Gemini CLI integration."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from hx.cli import main
from hx.gemini_integration import (
    gemini_status,
    install_gemini_config,
)
from hx.setup import run_setup


def _git_init(tmp_path: Path) -> None:
    subprocess.run(
        ["git", "init"], cwd=tmp_path, check=True, capture_output=True,
    )


def _init_repo(tmp_path: Path) -> None:
    _git_init(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("x = 1\n")
    run_setup(tmp_path)


def test_gemini_status_no_config(tmp_path: Path, monkeypatch: object) -> None:
    monkeypatch.setenv("GEMINI_HOME", str(tmp_path / ".gemini"))
    status = gemini_status()
    assert status.hx_configured is False


def test_install_gemini_config(tmp_path: Path, monkeypatch: object) -> None:
    _init_repo(tmp_path)
    gemini_home = tmp_path / ".gemini"
    monkeypatch.setenv("GEMINI_HOME", str(gemini_home))
    status = install_gemini_config(tmp_path)
    assert status.hx_configured is True
    # Verify JSON structure
    config = json.loads((gemini_home / "settings.json").read_text())
    assert "hx" in config["mcpServers"]
    assert "mcp" in config["mcpServers"]["hx"]["args"]


def test_install_preserves_existing(
    tmp_path: Path, monkeypatch: object,
) -> None:
    gemini_home = tmp_path / ".gemini"
    gemini_home.mkdir(parents=True)
    settings = gemini_home / "settings.json"
    settings.write_text(json.dumps({
        "mcpServers": {"other": {"command": "other-tool"}},
    }))
    monkeypatch.setenv("GEMINI_HOME", str(gemini_home))
    _init_repo(tmp_path)
    install_gemini_config(tmp_path)
    config = json.loads(settings.read_text())
    assert "other" in config["mcpServers"]
    assert "hx" in config["mcpServers"]


def test_gemini_setup_cli(tmp_path: Path, monkeypatch: object) -> None:
    _init_repo(tmp_path)
    monkeypatch.setenv("GEMINI_HOME", str(tmp_path / ".gemini"))
    rc = main([
        "--root", str(tmp_path), "--ui-mode", "quiet",
        "gemini", "setup",
    ])
    assert rc == 0


def test_gemini_status_cli(tmp_path: Path, monkeypatch: object) -> None:
    monkeypatch.setenv("GEMINI_HOME", str(tmp_path / ".gemini"))
    rc = main(["--ui-mode", "quiet", "gemini", "status"])
    assert rc == 0
