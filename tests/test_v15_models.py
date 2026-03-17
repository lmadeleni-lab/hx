"""Tests for model improvements: cell index, has_cell, TaskState.from_dict."""
from __future__ import annotations

import pytest

from hx.models import (
    Cell,
    HexMap,
    TaskState,
)


class TestHexMapCellIndex:
    """O(1) cell lookup via dict index."""

    def test_cell_lookup_is_indexed(self) -> None:
        cells = [Cell(cell_id=f"c{i}", paths=[], summary="") for i in range(100)]
        hexmap = HexMap(version="1", cells=cells)
        assert hexmap.cell("c50").cell_id == "c50"
        assert hexmap.cell("c99").cell_id == "c99"

    def test_has_cell(self) -> None:
        hexmap = HexMap(version="1", cells=[
            Cell(cell_id="a", paths=[], summary=""),
        ])
        assert hexmap.has_cell("a") is True
        assert hexmap.has_cell("b") is False

    def test_cell_raises_for_unknown(self) -> None:
        hexmap = HexMap(version="1", cells=[])
        with pytest.raises(KeyError, match="Unknown cell_id"):
            hexmap.cell("nonexistent")

    def test_to_dict_excludes_index(self) -> None:
        hexmap = HexMap(version="1", cells=[
            Cell(cell_id="a", paths=[], summary=""),
        ])
        d = hexmap.to_dict()
        assert "_cell_index" not in d


class TestTaskStateFromDict:
    """TaskState.from_dict filters unknown keys instead of crashing."""

    def test_ignores_unknown_keys(self) -> None:
        data = {
            "task_id": "t1",
            "status": "staged",
            "some_future_field": "value",
            "another_new_thing": 42,
        }
        task = TaskState.from_dict(data)
        assert task.task_id == "t1"
        assert task.status == "staged"

    def test_preserves_known_fields(self) -> None:
        data = {
            "task_id": "t2",
            "patch_sha256": "abc123",
        }
        task = TaskState.from_dict(data)
        assert task.patch_sha256 == "abc123"

    def test_round_trip(self) -> None:
        task = TaskState(task_id="t3", status="committed")
        d = task.to_dict()
        restored = TaskState.from_dict(d)
        assert restored.task_id == "t3"
        assert restored.status == "committed"
