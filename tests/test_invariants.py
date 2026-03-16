from __future__ import annotations

import tempfile
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from hx.audit import append_event, start_run
from hx.authz import AuthorizationError, allowed_cells, authorize_path
from hx.hexmap import save_hexmap
from hx.models import Cell, HexMap
from hx.policy import load_policy
from hx.replay import replay_run
from hx.templates import policy_toml


def write_policy(root: Path) -> None:
    (root / "POLICY.toml").write_text(policy_toml())


def write_linear_hexmap(root: Path) -> HexMap:
    for cell_id in ["a", "b", "c", "d"]:
        cell_dir = root / "src" / cell_id
        cell_dir.mkdir(parents=True, exist_ok=True)
        (cell_dir / "module.py").write_text(f'CELL = "{cell_id}"\n')

    hexmap = HexMap(
        version="1",
        cells=[
            Cell(
                cell_id="a",
                paths=["src/a/**"],
                summary="A",
                neighbors=["b", None, None, None, None, None],
            ),
            Cell(
                cell_id="b",
                paths=["src/b/**"],
                summary="B",
                neighbors=["c", None, None, "a", None, None],
            ),
            Cell(
                cell_id="c",
                paths=["src/c/**"],
                summary="C",
                neighbors=["d", None, None, "b", None, None],
            ),
            Cell(
                cell_id="d",
                paths=["src/d/**"],
                summary="D",
                neighbors=[None, None, None, "c", None, None],
            ),
        ],
    )
    save_hexmap(root, hexmap)
    return hexmap


@given(
    radius_pair=st.tuples(
        st.integers(min_value=0, max_value=3),
        st.integers(min_value=0, max_value=3),
    )
)
def test_allowed_cells_ball_is_monotonic(radius_pair: tuple[int, int]) -> None:
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        write_policy(root)
        hexmap = write_linear_hexmap(root)
        small_radius, large_radius = sorted(radius_pair)

        small = set(allowed_cells(hexmap, "a", small_radius))
        large = set(allowed_cells(hexmap, "a", large_radius))

        assert small.issubset(large)


@given(
    target_index=st.integers(min_value=0, max_value=3),
    radius_pair=st.tuples(
        st.integers(min_value=0, max_value=3),
        st.integers(min_value=0, max_value=3),
    ),
)
def test_authorization_is_monotonic_by_radius(
    target_index: int,
    radius_pair: tuple[int, int],
) -> None:
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        write_policy(root)
        hexmap = write_linear_hexmap(root)
        policy = load_policy(root)
        target_cell = ["a", "b", "c", "d"][target_index]
        target_path = f"src/{target_cell}/module.py"
        small_radius, large_radius = sorted(radius_pair)

        try:
            authorize_path(root, hexmap, policy, "a", small_radius, target_path)
        except AuthorizationError:
            return

        assert authorize_path(root, hexmap, policy, "a", large_radius, target_path) == target_cell


def test_replay_only_replays_recorded_command_events(tmp_path: Path) -> None:
    write_policy(tmp_path)
    write_linear_hexmap(tmp_path)
    run = start_run(tmp_path, "cmd.run", active_cell_id="a", radius=0, allowed=["a"])
    append_event(
        tmp_path,
        run.run_id,
        "cmd.run",
        {"command": "python3 -c 'print(1)'", "cwd": "src/a"},
    )
    append_event(
        tmp_path,
        run.run_id,
        "repo.stage_patch",
        {"task_id": "demo", "files_touched": ["src/demo.py"]},
    )

    replayed = replay_run(tmp_path, run.run_id)
    assert replayed["replayed_events"] == 1
    assert replayed["failed_events"] == 0
    assert replayed["results"][0]["command"] == "python3 -c 'print(1)'"
    assert replayed["results"][0]["ok"] is True


def test_replay_cannot_widen_command_set(tmp_path: Path) -> None:
    write_policy(tmp_path)
    write_linear_hexmap(tmp_path)
    run = start_run(tmp_path, "cmd.run", active_cell_id="a", radius=0, allowed=["a"])
    append_event(
        tmp_path,
        run.run_id,
        "cmd.run",
        {"command": "ls", "cwd": "src/a"},
    )

    replayed = replay_run(tmp_path, run.run_id)
    assert replayed["replayed_events"] == 0
    assert replayed["failed_events"] == 1
    assert "allowlist" in replayed["results"][0]["error"]


def test_replay_returns_structured_failure_when_context_is_missing(tmp_path: Path) -> None:
    write_policy(tmp_path)
    run = start_run(tmp_path, "cmd.run")
    append_event(
        tmp_path,
        run.run_id,
        "cmd.run",
        {"command": "python3 -c 'print(1)'", "cwd": "src/a"},
    )

    replayed = replay_run(tmp_path, run.run_id)
    assert replayed["replayed_events"] == 0
    assert replayed["failed_events"] == 1
    assert "Missing original active cell or radius" in replayed["results"][0]["error"]


def test_replay_reauthorizes_cwd_against_original_radius(tmp_path: Path) -> None:
    write_policy(tmp_path)
    write_linear_hexmap(tmp_path)
    run = start_run(tmp_path, "cmd.run", active_cell_id="a", radius=0, allowed=["a"])
    append_event(
        tmp_path,
        run.run_id,
        "cmd.run",
        {"command": "python3 -c 'print(1)'", "cwd": "src/b"},
    )

    replayed = replay_run(tmp_path, run.run_id)
    assert replayed["replayed_events"] == 0
    assert replayed["failed_events"] == 1
    assert "outside allowed radius" in replayed["results"][0]["error"]
