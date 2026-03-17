from __future__ import annotations

import io
import json
from pathlib import Path

from hx.cli import build_parser, doctor_problems, main, render_startup_screen
from hx.ui import (
    format_status_line,
)
from hx.ui import (
    render_startup_screen as render_colored_startup_screen,
)


def test_init_scaffolds_files(tmp_path: Path) -> None:
    assert main(["--root", str(tmp_path), "init"]) == 0
    assert (tmp_path / "AGENTS.md").exists()
    assert (tmp_path / "TOOLS.md").exists()
    assert (tmp_path / "HEXMAP.json").exists()
    assert (tmp_path / "POLICY.toml").exists()


def test_render_startup_screen_mentions_macos_prereqs() -> None:
    screen = render_startup_screen()
    assert "supported target: macOS terminal sessions" in screen
    assert "python3 (3.11+)" in screen
    assert "git (Xcode Command Line Tools is fine)" in screen
    assert "hx codex setup" in screen


def test_render_colored_startup_screen_can_include_ansi() -> None:
    screen = render_colored_startup_screen("0.1.0", color=True)
    assert "\033[" in screen
    assert "macOS terminal sessions" in screen


def test_main_without_command_returns_zero() -> None:
    assert main([]) == 0


def test_main_accepts_expanded_ui_mode() -> None:
    assert main(["--ui-mode", "expanded"]) == 0


def test_help_includes_startup_screen_for_tty(monkeypatch) -> None:
    monkeypatch.delenv("HX_NO_BANNER", raising=False)

    class TtyBuffer(io.StringIO):
        def isatty(self) -> bool:
            return True

    parser = build_parser()
    output = TtyBuffer()
    parser.print_help(output)
    text = output.getvalue()
    assert "supported target: macOS terminal sessions" in text


def test_doctor_problems_reports_non_macos(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("hx.cli.sys.platform", "linux")
    problems = doctor_problems(tmp_path)
    assert "hx currently supports macOS terminal workflows only" in problems


def test_format_status_line_includes_thinking_label() -> None:
    line = format_status_line("Indexing cell topology", kind="working", frame="⠋", color=False)
    assert "Indexing cell topology" in line
    assert "thinking" in line


def test_init_prints_codex_next_steps(tmp_path: Path, capsys) -> None:
    assert main(["--root", str(tmp_path), "--ui-mode", "quiet", "init"]) == 0
    out = capsys.readouterr().out
    assert "Next: hx codex setup" in out
    assert "Then: codex --login" in out


def test_codex_setup_writes_config(monkeypatch, tmp_path: Path, capsys) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    assert main(["--root", str(tmp_path), "--ui-mode", "quiet", "codex", "setup"]) == 0
    config = (fake_home / ".codex" / "config.toml").read_text()
    assert "[mcp_servers.hx]" in config
    assert str(tmp_path.resolve()) in config
    out = capsys.readouterr().out
    assert "codex --login" in out


def test_codex_status_reports_config(monkeypatch, tmp_path: Path, capsys) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    assert main(["--root", str(tmp_path), "--ui-mode", "quiet", "codex", "setup"]) == 0
    capsys.readouterr()
    assert main(["--root", str(tmp_path), "--ui-mode", "quiet", "codex", "status"]) == 0
    out = capsys.readouterr().out
    payload = json.loads(out.split("Next:", 1)[0])
    assert payload["hx_configured"] is True
