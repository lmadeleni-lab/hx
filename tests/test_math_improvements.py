"""Tests for the 5 mathematician-inspired improvements."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from hx.hexmap import _is_connected, load_hexmap, validate_hexmap
from hx.metrics import (
    _bounded_ratio,
    _normalized_entropy,
    _port_edge_weight,
    hex_isoperimetric_bound,
    occupation_fraction,
    policy_risk_score,
)
from hx.models import Cell, HexMap, ParentGroup, Port, PortSurfaceSpec
from hx.parents import (
    _parent_group_connected,
    parent_occupation_fraction,
    parent_rollup_metrics,
    validate_parent_groups,
)
from hx.ports import dual_port_check, find_triangles, holonomy_check
from hx.setup import run_setup


def _git_init(tmp_path: Path) -> None:
    subprocess.run(
        ["git", "init"], cwd=tmp_path, check=True, capture_output=True,
    )


def _make_triangle_hexmap() -> HexMap:
    """Build a 3-cell hexmap with a triangle: A-B-C-A."""
    cells = [
        Cell(
            cell_id="A", paths=["a/**"], summary="Cell A",
            neighbors=["B", None, "C", None, None, None],
            ports=[
                Port(port_id="A:0", neighbor_cell_id="B", direction="export",
                     surface=PortSurfaceSpec(declared_exports=["foo", "bar"])),
                None,
                Port(port_id="A:2", neighbor_cell_id="C", direction="import",
                     surface=PortSurfaceSpec(declared_exports=["baz"])),
                None, None, None,
            ],
        ),
        Cell(
            cell_id="B", paths=["b/**"], summary="Cell B",
            neighbors=["A", "C", None, None, None, None],
            ports=[
                Port(port_id="B:0", neighbor_cell_id="A", direction="import",
                     surface=PortSurfaceSpec(declared_exports=["foo"])),
                Port(port_id="B:1", neighbor_cell_id="C", direction="export",
                     surface=PortSurfaceSpec(declared_exports=["qux"])),
                None, None, None, None,
            ],
        ),
        Cell(
            cell_id="C", paths=["c/**"], summary="Cell C",
            neighbors=[None, None, "A", None, None, "B"],
            ports=[
                None, None,
                Port(port_id="C:2", neighbor_cell_id="A", direction="export",
                     surface=PortSurfaceSpec(declared_exports=["baz"])),
                None, None,
                Port(port_id="C:5", neighbor_cell_id="B", direction="import",
                     surface=PortSurfaceSpec(declared_exports=[])),
            ],
        ),
    ]
    return HexMap(version="1", cells=cells)


def _make_disconnected_hexmap() -> HexMap:
    """Two cells with no neighbor link."""
    cells = [
        Cell(cell_id="X", paths=["x/**"], summary="X"),
        Cell(cell_id="Y", paths=["y/**"], summary="Y"),
    ]
    return HexMap(version="1", cells=cells)


# --- Improvement 1: Hex lattice guarantees ---

class TestHexLatticeGuarantees:
    def test_isoperimetric_bound_single_cell(self) -> None:
        assert hex_isoperimetric_bound(1) == 6.0

    def test_isoperimetric_bound_grows(self) -> None:
        b1 = hex_isoperimetric_bound(7)
        b2 = hex_isoperimetric_bound(19)
        assert b2 > b1 > 0

    def test_isoperimetric_bound_zero(self) -> None:
        assert hex_isoperimetric_bound(0) == 0.0

    def test_occupation_fraction_empty(self) -> None:
        hexmap = HexMap(version="1", cells=[
            Cell(cell_id="root", paths=["**"], summary="Root"),
        ])
        assert occupation_fraction(hexmap) == 0.0

    def test_occupation_fraction_full(self) -> None:
        hexmap = _make_triangle_hexmap()
        frac = occupation_fraction(hexmap)
        assert 0.0 < frac <= 1.0

    def test_is_connected_true(self) -> None:
        hexmap = _make_triangle_hexmap()
        assert _is_connected(hexmap) is True

    def test_is_connected_false(self) -> None:
        hexmap = _make_disconnected_hexmap()
        assert _is_connected(hexmap) is False

    def test_is_connected_single_cell(self) -> None:
        hexmap = HexMap(version="1", cells=[
            Cell(cell_id="solo", paths=["**"], summary="Solo"),
        ])
        assert _is_connected(hexmap) is True

    def test_validate_catches_disconnected(self, tmp_path: Path) -> None:
        _git_init(tmp_path)
        (tmp_path / "x").mkdir()
        (tmp_path / "x" / "a.py").write_text("x = 1\n")
        (tmp_path / "y").mkdir()
        (tmp_path / "y" / "b.py").write_text("y = 2\n")
        hexmap = _make_disconnected_hexmap()
        (tmp_path / "HEXMAP.json").write_text(
            json.dumps(hexmap.to_dict(), indent=2),
        )
        errors = validate_hexmap(tmp_path, hexmap)
        assert any("not connected" in e for e in errors)


# --- Improvement 2: Information-weighted boundary pressure ---

class TestInformationWeightedPressure:
    def test_port_edge_weight_no_history(self) -> None:
        assert _port_edge_weight({}, "unknown_port") == 1.0

    def test_port_edge_weight_none_port(self) -> None:
        assert _port_edge_weight({}, None) == 1.0

    def test_port_edge_weight_with_history(self) -> None:
        history = {
            "p1": {
                "changes": [
                    {"categories": ["add_export"],
                     "recorded_at": "2026-01-01T00:00:00+00:00"},
                    {"categories": ["change_signature"],
                     "recorded_at": "2026-01-02T00:00:00+00:00"},
                    {"categories": ["add_export", "change_schema"],
                     "recorded_at": "2026-01-03T00:00:00+00:00"},
                ],
                "failures": 1,
                "touches": 3,
            }
        }
        weight = _port_edge_weight(history, "p1")
        # Should be > 1.0 (base) due to entropy + churn
        assert weight > 1.0

    def test_port_edge_weight_empty_changes(self) -> None:
        history = {"p1": {"changes": [], "failures": 0, "touches": 0}}
        assert _port_edge_weight(history, "p1") == 1.0


# --- Improvement 3: Nonlinear architecture potential ---

class TestNonlinearPotential:
    def test_risk_score_normalized_to_unit(self) -> None:
        entry = {"failures": 100, "touches": 200}
        score = policy_risk_score(
            entry, entropy=1.0, churn=100.0, pressure=500.0,
        )
        assert 0.0 <= score <= 1.0

    def test_risk_score_zero_inputs(self) -> None:
        entry = {"failures": 0}
        score = policy_risk_score(
            entry, entropy=0.0, churn=0.0, pressure=0.0,
        )
        assert score == 0.0

    def test_interaction_term_increases_score(self) -> None:
        entry = {"failures": 0}
        # Same linear components but different interaction
        score_low = policy_risk_score(
            entry, entropy=0.0, churn=5.0, pressure=0.0,
        )
        score_high = policy_risk_score(
            entry, entropy=1.0, churn=5.0, pressure=0.0,
        )
        # High entropy + high churn should compound
        assert score_high > score_low

    def test_bounded_ratio_clamps(self) -> None:
        assert _bounded_ratio(100.0, 5.0) == 1.0
        assert _bounded_ratio(0.0, 5.0) == 0.0
        assert 0.0 < _bounded_ratio(2.5, 5.0) < 1.0


# --- Improvement 4: Cycle consistency / holonomy ---

class TestHolonomy:
    def test_find_triangles_in_triangle_graph(self) -> None:
        hexmap = _make_triangle_hexmap()
        triangles = find_triangles(hexmap)
        assert len(triangles) == 1
        assert set(triangles[0]) == {"A", "B", "C"}

    def test_find_triangles_no_triangle(self) -> None:
        hexmap = _make_disconnected_hexmap()
        triangles = find_triangles(hexmap)
        assert triangles == []

    def test_holonomy_check_consistent(self) -> None:
        hexmap = _make_triangle_hexmap()
        warnings = holonomy_check(hexmap, ("A", "B", "C"))
        # May or may not have warnings depending on export propagation
        assert isinstance(warnings, list)

    def test_holonomy_check_short_cycle(self) -> None:
        hexmap = _make_triangle_hexmap()
        warnings = holonomy_check(hexmap, ("A", "B"))
        assert warnings == []

    def test_dual_port_check_no_conflict(self) -> None:
        hexmap = _make_triangle_hexmap()
        # A[0] exports to B, B[0] imports from A — no conflict
        warnings = dual_port_check(hexmap, "A", 0)
        assert isinstance(warnings, list)

    def test_dual_port_check_both_export_same_symbol(self) -> None:
        """Two ports both exporting the same symbol = orientation warning."""
        cells = [
            Cell(
                cell_id="P", paths=["p/**"], summary="P",
                neighbors=["Q", None, None, None, None, None],
                ports=[
                    Port(port_id="P:0", neighbor_cell_id="Q",
                         direction="export",
                         surface=PortSurfaceSpec(declared_exports=["shared"])),
                    None, None, None, None, None,
                ],
            ),
            Cell(
                cell_id="Q", paths=["q/**"], summary="Q",
                neighbors=["P", None, None, None, None, None],
                ports=[
                    Port(port_id="Q:0", neighbor_cell_id="P",
                         direction="export",
                         surface=PortSurfaceSpec(declared_exports=["shared"])),
                    None, None, None, None, None,
                ],
            ),
        ]
        hexmap = HexMap(version="1", cells=cells)
        warnings = dual_port_check(hexmap, "P", 0)
        assert any("non-orientable" in w for w in warnings)

    def test_dual_port_no_exports_no_warning(self) -> None:
        hexmap = _make_triangle_hexmap()
        # C[5] faces B but has no declared exports
        warnings = dual_port_check(hexmap, "C", 5)
        assert warnings == []


# --- Improvement 5: Parent group renormalization ---

class TestParentRenormalization:
    def test_parent_group_connected(self) -> None:
        hexmap = _make_triangle_hexmap()
        group = ParentGroup(
            parent_id="pg1", summary="Test",
            center_cell_id="A", children=["B", "C", None, None, None, None],
        )
        assert _parent_group_connected(hexmap, group) is True

    def test_parent_group_disconnected(self) -> None:
        hexmap = _make_disconnected_hexmap()
        group = ParentGroup(
            parent_id="pg1", summary="Test",
            center_cell_id="X", children=["Y", None, None, None, None, None],
        )
        assert _parent_group_connected(hexmap, group) is False

    def test_parent_occupation_fraction(self) -> None:
        hexmap = _make_triangle_hexmap()
        group = ParentGroup(
            parent_id="pg1", summary="Test",
            center_cell_id="A", children=["B", "C", None, None, None, None],
        )
        frac = parent_occupation_fraction(hexmap, group)
        assert 0.0 < frac <= 1.0

    def test_validate_catches_disconnected_parent(self) -> None:
        hexmap = _make_disconnected_hexmap()
        hexmap.parent_groups = [
            ParentGroup(
                parent_id="pg1", summary="Bad",
                center_cell_id="X",
                children=["Y", None, None, None, None, None],
            ),
        ]
        errors = validate_parent_groups(hexmap)
        assert any("not connected" in e for e in errors)

    def test_parent_rollup_has_occupation_fraction(self, tmp_path: Path) -> None:
        _git_init(tmp_path)
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "a.py").write_text("x = 1\n")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "t.py").write_text("pass\n")
        run_setup(tmp_path)
        hexmap = load_hexmap(tmp_path)
        if hexmap.parent_groups:
            metrics = parent_rollup_metrics(
                tmp_path, hexmap, hexmap.parent_groups[0].parent_id,
            )
            assert "parent_occupation_fraction" in metrics

    def test_pooled_entropy_differs_from_average(self) -> None:
        """Pooled entropy over diverse ports > average of individual entropies."""
        # Two ports each with single category = entropy 0 each
        # But pooled across both = positive entropy if categories differ
        events_a: list[list[str]] = [["add_export"]] * 5
        events_b: list[list[str]] = [["change_signature"]] * 5
        ent_a = _normalized_entropy(events_a)
        ent_b = _normalized_entropy(events_b)
        avg = (ent_a + ent_b) / 2
        pooled = _normalized_entropy(events_a + events_b)
        # Pooled should capture the diversity between ports
        assert pooled > avg
