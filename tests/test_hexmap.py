from __future__ import annotations

from pathlib import Path

from hx.audit import append_event, finish_run, start_run
from hx.cli import main
from hx.hexmap import build_hexmap, save_hexmap, validate_hexmap
from hx.models import Cell, HexMap, ParentGroup, Port
from hx.parents import derive_parent_groups, validate_parent_groups
from hx.ui import render_hex_view, render_parent_watch_dashboard, render_watch_dashboard


def test_build_hexmap_creates_cells(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    hexmap = build_hexmap(tmp_path)
    assert {cell.cell_id for cell in hexmap.cells} == {"src", "tests"}
    assert hexmap.parent_groups


def test_validate_hexmap_flags_missing_paths(tmp_path: Path) -> None:
    hexmap = build_hexmap(tmp_path)
    errors = validate_hexmap(tmp_path, hexmap)
    assert errors


def test_derive_parent_groups_is_deterministic_with_overrides() -> None:
    hexmap = HexMap(
        version="1",
        cells=[
            Cell(
                cell_id="a",
                paths=["src/a/**"],
                summary="A",
                neighbors=["b", "c", None, None, None, None],
            ),
            Cell(
                cell_id="b",
                paths=["src/b/**"],
                summary="B",
                neighbors=[None, None, None, "a", None, None],
            ),
            Cell(
                cell_id="c",
                paths=["src/c/**"],
                summary="C",
                neighbors=[None, None, None, None, None, "a"],
            ),
        ],
    )
    existing = [
        ParentGroup(
            parent_id="parent-a",
            summary="custom",
            center_cell_id="a",
            overrides={"children": ["b", None, None, None, None, None]},
        )
    ]
    derived = derive_parent_groups(hexmap, existing)
    assert derived[0].parent_id == "parent-a"
    assert derived[0].summary == "custom"
    assert derived[0].children[0] == "b"


def test_validate_parent_groups_catches_duplicate_children() -> None:
    hexmap = HexMap(
        version="1",
        cells=[
            Cell(cell_id="a", paths=["a/**"], summary="A"),
            Cell(cell_id="b", paths=["b/**"], summary="B"),
            Cell(cell_id="c", paths=["c/**"], summary="C"),
        ],
        parent_groups=[
            ParentGroup(
                parent_id="p1",
                summary="P1",
                center_cell_id="a",
                children=["b", None, None, None, None, None],
            ),
            ParentGroup(
                parent_id="p2",
                summary="P2",
                center_cell_id="c",
                children=["b", None, None, None, None, None],
            ),
        ],
    )
    errors = validate_parent_groups(hexmap)
    assert any("already assigned" in error for error in errors)


def test_render_hex_view_reports_neighbor_fulfillment() -> None:
    hexmap = HexMap(
        version="1",
        cells=[
            Cell(
                cell_id="core",
                paths=["src/core/**"],
                summary="core",
                neighbors=["api", "db", None, None, None, None],
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
            Cell(
                cell_id="db",
                paths=["src/db/**"],
                summary="db",
                neighbors=[None, None, None, None, None, "core"],
            ),
        ],
    )
    view = render_hex_view(hexmap, "core", 1, color=False)
    assert "Hex view for core (R1)" in view
    assert "fulfilled sides: 1/6" in view
    assert "neighbor-only" in view
    assert "allowed cells: api, core, db" in view


def test_hex_show_command_renders_ascii_view(tmp_path: Path, capsys) -> None:
    (tmp_path / "src" / "core").mkdir(parents=True)
    (tmp_path / "src" / "api").mkdir(parents=True)
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
    save_hexmap(tmp_path, hexmap)
    assert main(["--root", str(tmp_path), "--ui-mode", "quiet", "hex", "show", "core"]) == 0
    out = capsys.readouterr().out
    assert "Hex view for core (R1)" in out
    assert "fulfilled" in out


def test_render_watch_dashboard_includes_runs_and_events(tmp_path: Path) -> None:
    run = start_run(tmp_path, "cmd.run", active_cell_id="core", radius=1, allowed=["core", "api"])
    append_event(
        tmp_path,
        run.run_id,
        "cmd.run",
        {"command": "python3 -c 'print(1)'", "cwd": "src/core"},
    )
    finish_run(tmp_path, run.run_id, "ok")
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
    dashboard = render_watch_dashboard(
        hexmap,
        "core",
        1,
        [run],
        tick=1,
        interval_s=0.2,
        parent_details=None,
        color=False,
        width=100,
    )
    assert "hx hex watch" in dashboard
    assert "Recent Runs" in dashboard
    assert "Recent Events" in dashboard
    assert "cmd.run" in dashboard


def test_hex_watch_command_renders_dashboard_once(tmp_path: Path, capsys) -> None:
    (tmp_path / "src" / "core").mkdir(parents=True)
    (tmp_path / "src" / "api").mkdir(parents=True)
    run = start_run(tmp_path, "cmd.run", active_cell_id="core", radius=1, allowed=["core", "api"])
    append_event(
        tmp_path,
        run.run_id,
        "cmd.run",
        {"command": "python3 -c 'print(1)'", "cwd": "src/core"},
    )
    finish_run(tmp_path, run.run_id, "ok")
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
    save_hexmap(tmp_path, hexmap)
    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "--ui-mode",
                "quiet",
                "hex",
                "watch",
                "core",
                "--radius",
                "1",
                "--interval",
                "0.01",
                "--iterations",
                "1",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "Hex Neighborhood" in out
    assert "Recent Events" in out


def test_hex_parent_show_and_summarize_commands(tmp_path: Path, capsys) -> None:
    (tmp_path / "src" / "core").mkdir(parents=True)
    (tmp_path / "src" / "api").mkdir(parents=True)
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
    assert (
        main(
            ["--root", str(tmp_path), "--ui-mode", "quiet", "hex", "parent", "show", "parent_core"]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "Parent view for parent_core" in out
    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "--ui-mode",
                "quiet",
                "hex",
                "parent",
                "summarize",
                "parent_core",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert '"parent_id": "parent_core"' in out


def test_render_parent_watch_dashboard_includes_parent_panels(tmp_path: Path) -> None:
    run = start_run(
        tmp_path,
        "repo.commit_patch",
        active_cell_id="core",
        radius=1,
        allowed=["core", "api"],
    )
    append_event(
        tmp_path,
        run.run_id,
        "repo.commit_patch",
        {"task_id": "demo"},
    )
    finish_run(tmp_path, run.run_id, "ok")
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
    dashboard = render_parent_watch_dashboard(
        hexmap,
        tmp_path,
        "parent_core",
        [run],
        tick=1,
        interval_s=0.2,
        color=False,
        width=100,
    )
    assert "hx parent watch" in dashboard
    assert "Neighboring Parents" in dashboard
    assert "Parent Summary" in dashboard
