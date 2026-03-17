"""Tests for the stateful reasoning engine."""
from __future__ import annotations

import subprocess
from pathlib import Path

from hx.cli import main
from hx.reasoning import (
    ReasoningMode,
    build_scoped_prompt,
    check_feedback_integrity,
    percolation_status,
    reasoning_gate,
    transition_state,
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


# --- Reasoning Gate ---

class TestReasoningGate:
    def test_returns_valid_mode(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        result = reasoning_gate(tmp_path, "src", 1)
        valid_modes = {m.value for m in ReasoningMode}
        assert result["mode"] in valid_modes

    def test_returns_signals(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        result = reasoning_gate(tmp_path, "src", 1)
        signals = result["signals"]
        assert "occupation_fraction" in signals
        assert "boundary_pressure" in signals
        assert "max_port_risk" in signals

    def test_local_mode_for_clean_repo(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        result = reasoning_gate(tmp_path, "src", 0)
        # Clean repo with no history should be LOCAL
        assert result["mode"] == ReasoningMode.LOCAL.value

    def test_returns_justification(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        result = reasoning_gate(tmp_path, "src", 1)
        assert len(result["justification"]) > 0

    def test_no_hexmap_returns_full(self, tmp_path: Path) -> None:
        _git_init(tmp_path)
        result = reasoning_gate(tmp_path, "root", 0)
        assert result["mode"] == ReasoningMode.LLM_FULL.value

    def test_hot_edges_list(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        result = reasoning_gate(tmp_path, "src", 1)
        assert isinstance(result["hot_edges"], list)


# --- State Transitions ---

class TestStateTransitions:
    def test_transition_writes_log(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        action = {"type": "tool_call", "tool": "repo.read"}
        outcome = {
            "status": "ok",
            "cells_affected": ["src"],
            "ports_affected": [],
        }
        delta = transition_state(tmp_path, action, outcome)
        assert delta["action_type"] == "tool_call"
        assert delta["risk_direction"] == "stable"
        # Check log file exists
        log = tmp_path / ".hx" / "state" / "transitions.jsonl"
        assert log.exists()
        lines = log.read_text().strip().split("\n")
        assert len(lines) == 1

    def test_multiple_transitions_append(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        for i in range(3):
            transition_state(
                tmp_path,
                {"type": "step", "tool": f"tool_{i}"},
                {"status": "ok", "cells_affected": [], "ports_affected": []},
            )
        log = tmp_path / ".hx" / "state" / "transitions.jsonl"
        lines = log.read_text().strip().split("\n")
        assert len(lines) == 3

    def test_transition_captures_timestamp(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        delta = transition_state(
            tmp_path,
            {"type": "test"},
            {"status": "ok", "cells_affected": [], "ports_affected": []},
        )
        assert "timestamp" in delta


# --- Feedback Integrity ---

class TestFeedbackIntegrity:
    def test_no_affected_ports_returns_empty(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        warnings = check_feedback_integrity(tmp_path, [])
        assert warnings == []

    def test_unknown_ports_returns_empty(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        warnings = check_feedback_integrity(tmp_path, ["nonexistent"])
        assert warnings == []

    def test_no_hexmap_returns_empty(self, tmp_path: Path) -> None:
        _git_init(tmp_path)
        warnings = check_feedback_integrity(tmp_path, ["some_port"])
        assert warnings == []


# --- Percolation Monitor ---

class TestPercolationMonitor:
    def test_returns_status(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        status = percolation_status(tmp_path)
        assert status["available"] is True
        assert "global_occupation" in status
        assert "global_phase" in status
        assert "recommendation" in status

    def test_no_hexmap(self, tmp_path: Path) -> None:
        _git_init(tmp_path)
        status = percolation_status(tmp_path)
        assert status["available"] is False

    def test_subcritical_phase(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        status = percolation_status(tmp_path)
        # Clean repo should be subcritical (no ports)
        assert status["global_phase"] == "subcritical"

    def test_includes_parent_groups(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        status = percolation_status(tmp_path)
        assert isinstance(status.get("parent_groups"), list)


# --- Scoped Prompt ---

class TestScopedPrompt:
    def test_builds_focused_prompt(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        hot_edges = [
            {"from": "src", "to": "tests", "risk": 0.5, "weight": 2.5},
        ]
        prompt = build_scoped_prompt(
            tmp_path, "src", 1, hot_edges, "Fix the bug",
        )
        assert "SCOPED MODE" in prompt
        assert "src" in prompt
        assert "Fix the bug" in prompt
        assert "risk=" in prompt

    def test_empty_hot_edges(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        prompt = build_scoped_prompt(
            tmp_path, "src", 0, [], "Do something",
        )
        assert "SCOPED MODE" in prompt


# --- CLI Integration ---

class TestCLIIntegration:
    def test_percolation_cli(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        rc = main([
            "--root", str(tmp_path), "--ui-mode", "quiet",
            "percolation",
        ])
        assert rc == 0

    def test_percolation_cli_json(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        rc = main([
            "--root", str(tmp_path), "--ui-mode", "quiet",
            "percolation", "--json",
        ])
        assert rc == 0

    def test_gate_cli(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        from hx.hexmap import load_hexmap
        hexmap = load_hexmap(tmp_path)
        cell_id = hexmap.cells[0].cell_id
        rc = main([
            "--root", str(tmp_path), "--ui-mode", "quiet",
            "gate", "--cell", cell_id,
        ])
        assert rc == 0

    def test_gate_cli_json(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        from hx.hexmap import load_hexmap
        hexmap = load_hexmap(tmp_path)
        cell_id = hexmap.cells[0].cell_id
        rc = main([
            "--root", str(tmp_path), "--ui-mode", "quiet",
            "gate", "--cell", cell_id, "--json",
        ])
        assert rc == 0
