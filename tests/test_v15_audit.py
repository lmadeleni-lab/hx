"""Tests for v1.5 audit improvements (file locking, atomic writes)."""
from __future__ import annotations

from pathlib import Path

from hx.audit import (
    append_event,
    finish_run,
    list_runs,
    load_run,
    save_run,
    start_run,
    update_run,
)
from hx.config import ensure_hx_dirs


class TestAuditAtomicWrites:
    """save_run uses atomic write via tmp file rename."""

    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        ensure_hx_dirs(tmp_path)
        run = start_run(tmp_path, "test.cmd")
        loaded = load_run(tmp_path, run.run_id)
        assert loaded.run_id == run.run_id
        assert loaded.command == "test.cmd"

    def test_no_tmp_files_left_behind(self, tmp_path: Path) -> None:
        ensure_hx_dirs(tmp_path)
        run = start_run(tmp_path, "clean.cmd")
        save_run(tmp_path, run)
        audit_dir = tmp_path / ".hx" / "audit"
        tmp_files = list(audit_dir.glob("*.tmp"))
        assert tmp_files == []


class TestAuditLocking:
    """append_event and update_run use file locking."""

    def test_append_event_preserves_existing_events(self, tmp_path: Path) -> None:
        ensure_hx_dirs(tmp_path)
        run = start_run(tmp_path, "multi-event")
        append_event(tmp_path, run.run_id, "event.a", {"key": "val1"})
        append_event(tmp_path, run.run_id, "event.b", {"key": "val2"})
        append_event(tmp_path, run.run_id, "event.c", {"key": "val3"})

        loaded = load_run(tmp_path, run.run_id)
        assert len(loaded.events) == 3
        assert loaded.events[0].event_type == "event.a"
        assert loaded.events[1].event_type == "event.b"
        assert loaded.events[2].event_type == "event.c"

    def test_update_run_preserves_events(self, tmp_path: Path) -> None:
        ensure_hx_dirs(tmp_path)
        run = start_run(tmp_path, "update-test")
        append_event(tmp_path, run.run_id, "before.update", {})
        update_run(tmp_path, run.run_id, status="working")

        loaded = load_run(tmp_path, run.run_id)
        assert loaded.status == "working"
        assert len(loaded.events) == 1

    def test_finish_run_sets_status_and_timestamp(self, tmp_path: Path) -> None:
        ensure_hx_dirs(tmp_path)
        run = start_run(tmp_path, "finish-test")
        finish_run(tmp_path, run.run_id, "ok")

        loaded = load_run(tmp_path, run.run_id)
        assert loaded.status == "ok"
        assert loaded.finished_at is not None

    def test_list_runs_returns_all(self, tmp_path: Path) -> None:
        ensure_hx_dirs(tmp_path)
        start_run(tmp_path, "cmd1")
        start_run(tmp_path, "cmd2")
        start_run(tmp_path, "cmd3")

        runs = list_runs(tmp_path)
        assert len(runs) == 3
