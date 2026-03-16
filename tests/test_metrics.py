from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from hx.audit import finish_run, start_run, update_run
from hx.config import ensure_hx_dirs
from hx.hexmap import save_hexmap
from hx.metrics import (
    _boundary_pressure_heuristic,
    _decayed_churn,
    _normalized_entropy,
    _weighted_proof_coverage,
    boundary_pressure,
    compute_metrics,
    load_port_history,
    record_port_change,
    save_port_history,
    summarize_runs,
    top_risky_ports,
)
from hx.models import Cell, HexMap, Port
from hx.parents import derive_parent_groups, parent_report_markdown, parent_rollup_metrics


def test_metrics_compute_and_risk(tmp_path: Path) -> None:
    ensure_hx_dirs(tmp_path)
    record_port_change(
        tmp_path,
        "task-1",
        [{"port_id": "p1", "categories": ["add_export", "change_signature"]}],
        success=True,
    )
    task = {
        "radius": 1,
        "files_touched": ["src/a.py"],
        "port_check": {
            "touched_cells": ["a", "b"],
            "impacted_ports": [{"port_id": "p1"}],
            "obligations": {"required_checks": ["pytest -q"]},
            "cross_cell_imports": 1,
        },
        "proofs": {"checks": [{"returncode": 0}]},
    }
    metrics = compute_metrics(tmp_path, task)
    assert metrics["boundary_pressure_heuristic"] > 0
    assert 0.0 <= metrics["port_entropy"] <= 1.0
    assert metrics["port_entropy_raw"] >= metrics["port_entropy"]
    assert metrics["port_churn_raw"] >= metrics["port_churn"]
    assert metrics["proof_coverage_raw"] == 1.0
    assert 0.0 <= metrics["architecture_potential"] <= 1.0
    assert metrics["architecture_potential_components"]["boundary_pressure"] > 0.0
    assert top_risky_ports(tmp_path, 1)[0]["port_id"] == "p1"


def test_normalized_entropy_scales_to_one_for_uniform_categories() -> None:
    category_events = [
        ["add_export"],
        ["remove_export"],
        ["change_signature"],
        ["change_schema"],
        ["change_invariant"],
        ["change_tests_required"],
    ]
    assert _normalized_entropy(category_events) == 1.0


def test_decayed_churn_weights_recent_changes_more_heavily(tmp_path: Path) -> None:
    ensure_hx_dirs(tmp_path)
    record_port_change(
        tmp_path,
        "task-recent",
        [{"port_id": "p1", "categories": ["add_export"]}],
        success=True,
    )
    history = load_port_history(tmp_path)
    old_timestamp = (datetime.now(UTC) - timedelta(days=60)).isoformat()
    history["p1"]["changes"].append(
        {
            "task_id": "task-old",
            "categories": ["remove_export"],
            "recorded_at": old_timestamp,
        }
    )
    save_port_history(tmp_path, history)

    changes = history["p1"]["changes"]
    decayed = _decayed_churn(changes)
    assert len(changes) == 2
    assert 1.0 < decayed < 2.0


def test_boundary_pressure_uses_graph_cut_when_hexmap_exists(tmp_path: Path) -> None:
    hexmap = HexMap(
        version="1",
        cells=[
            Cell(
                cell_id="a",
                paths=["a/**"],
                summary="A",
                neighbors=["b", None, None, None, None, None],
            ),
            Cell(
                cell_id="b",
                paths=["b/**"],
                summary="B",
                neighbors=[None, None, None, "a", None, None],
            ),
        ],
    )
    save_hexmap(tmp_path, hexmap)
    task = {
        "radius": 1,
        "port_check": {
            "allowed_cells": ["a"],
            "touched_cells": ["a"],
            "cross_cell_imports": 1,
        },
    }
    assert boundary_pressure(tmp_path, task) == 1.0
    assert _boundary_pressure_heuristic(task) > boundary_pressure(tmp_path, task)


def test_weighted_proof_coverage_uses_obligation_weights() -> None:
    task = {
        "port_check": {
            "obligations": {
                "check_specs": [
                    {
                        "value": "pytest -q tests/a.py",
                        "class": "port_declared_check",
                        "weight": 1.0,
                    },
                    {
                        "value": "pytest -q tests/b.py",
                        "class": "cell_escalation_check",
                        "weight": 1.25,
                    },
                ],
                "artifact_specs": [
                    {
                        "value": ".hx/artifacts/task/port_check.json",
                        "class": "governance_artifact",
                        "weight": 0.5,
                    },
                    {
                        "value": ".hx/artifacts/task/risk_report.json",
                        "class": "risk_report_artifact",
                        "weight": 0.75,
                    },
                ],
            }
        },
        "proofs": {
            "checks": [
                {"command": "pytest -q tests/a.py", "returncode": 0},
                {"command": "pytest -q tests/b.py", "returncode": 1},
            ],
            "artifacts": [".hx/artifacts/task/port_check.json"],
        },
    }

    weighted, raw = _weighted_proof_coverage(task)
    assert weighted == 0.429
    assert raw == 0.5


def test_summarize_runs_includes_architecture_potential(tmp_path: Path) -> None:
    ensure_hx_dirs(tmp_path)
    first = start_run(tmp_path, "repo.commit_patch", active_cell_id="a", radius=0)
    update_run(
        tmp_path,
        first.run_id,
        metrics={
            "proof_coverage": 1.0,
            "architecture_potential": 0.25,
            "architecture_potential_components": {
                "approval_rate": 0.0,
                "boundary_pressure": 0.2,
            },
        },
    )
    finish_run(tmp_path, first.run_id, "ok")

    second = start_run(tmp_path, "repo.commit_patch", active_cell_id="b", radius=1)
    update_run(
        tmp_path,
        second.run_id,
        metrics={
            "proof_coverage": 0.5,
            "architecture_potential": 0.75,
            "architecture_potential_components": {
                "approval_rate": 1.0,
                "boundary_pressure": 0.6,
            },
        },
    )
    finish_run(tmp_path, second.run_id, "ok")

    summary = summarize_runs(tmp_path)
    assert summary["runs"] == 2
    assert summary["architecture_potential"] == 0.5
    assert summary["approval_rate"] == 0.5
    assert summary["architecture_potential_components"]["boundary_pressure"] == 0.4


def test_parent_rollup_metrics_and_report(tmp_path: Path) -> None:
    hexmap = HexMap(
        version="1",
        cells=[
            Cell(
                cell_id="core",
                paths=["src/core/**"],
                summary="core",
                neighbors=["api", None, None, None, None, None],
                ports=[
                    Port(port_id="core-api", neighbor_cell_id="api"),
                    None,
                    None,
                    None,
                    None,
                    None,
                ],
            ),
            Cell(
                cell_id="api",
                paths=["src/api/**"],
                summary="api",
                neighbors=[None, None, None, "core", None, None],
            ),
        ],
    )
    hexmap.parent_groups = derive_parent_groups(hexmap)
    save_hexmap(tmp_path, hexmap)
    record_port_change(
        tmp_path,
        "task-parent",
        [{"port_id": "core-api", "categories": ["add_export"]}],
        success=True,
    )
    metrics = parent_rollup_metrics(tmp_path, hexmap, "parent_core")
    assert metrics["parent_boundary_pressure"] == 0.0
    assert metrics["parent_architecture_potential"] >= 0.0
    report = parent_report_markdown(tmp_path, hexmap, "parent_core")
    assert "hx parent metrics report" in report
    assert "parent_id: `parent_core`" in report
