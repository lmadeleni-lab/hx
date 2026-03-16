from __future__ import annotations

import difflib
import json
import subprocess
from pathlib import Path

import pytest

from hx.audit import load_run
from hx.authz import AuthorizationError, authorize_path
from hx.hexmap import load_hexmap, save_hexmap
from hx.metrics import record_port_change
from hx.models import (
    Cell,
    HexMap,
    Port,
    PortApproval,
    PortCompat,
    PortProof,
    PortSurfaceSpec,
)
from hx.policy import load_policy
from hx.ports import check_task_ports
from hx.proof import collect_task_proofs, run_allowed_command, verify_task_proofs
from hx.repo_ops import approve_patch, commit_patch, load_task, save_task, stage_patch
from hx.templates import policy_toml


def write_policy(root: Path, *, mode: str = "dev") -> None:
    (root / "POLICY.toml").write_text(policy_toml().replace('mode = "dev"', f'mode = "{mode}"'))


def init_git_repo(root: Path) -> None:
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)


def make_patch(path: str, before: str, after: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )


def make_two_cell_hexmap() -> HexMap:
    port = Port(
        port_id="src-tests",
        neighbor_cell_id="tests",
        direction="out",
        surface=PortSurfaceSpec(),
        compat=PortCompat(),
        proof=PortProof(),
        approval=PortApproval(breaking_requires_human=True),
    )
    return HexMap(
        version="1",
        cells=[
            Cell(
                cell_id="src",
                paths=["src/**"],
                summary="Source cell",
                tests=["pytest -q tests/test_demo.py"],
                neighbors=["tests", None, None, None, None, None],
                ports=[port, None, None, None, None, None],
            ),
            Cell(
                cell_id="tests",
                paths=["tests/**"],
                summary="Test cell",
                tests=["pytest -q tests/test_demo.py"],
                neighbors=[None, None, None, "src", None, None],
                ports=[None, None, None, None, None, None],
            ),
        ],
    )


def init_governed_repo(root: Path, *, mode: str = "dev") -> None:
    init_git_repo(root)
    (root / "src").mkdir()
    (root / "tests").mkdir()
    (root / "src" / "api.py").write_text(
        "def greet(name):\n"
        "    return name\n"
    )
    (root / "tests" / "test_demo.py").write_text(
        "from src.api import greet\n\n"
        "def test_greet():\n"
        '    assert greet("x") == "x"\n'
    )
    save_hexmap(root, make_two_cell_hexmap())
    write_policy(root, mode=mode)


def test_authorize_path_denies_sandboxed_and_out_of_radius(tmp_path: Path) -> None:
    init_governed_repo(tmp_path)
    (tmp_path / ".env").write_text("SECRET=1\n")
    hexmap = load_hexmap(tmp_path)
    policy = load_policy(tmp_path)

    with pytest.raises(AuthorizationError, match="sandbox"):
        authorize_path(tmp_path, hexmap, policy, "src", 0, ".env")

    with pytest.raises(AuthorizationError, match="outside allowed radius"):
        authorize_path(tmp_path, hexmap, policy, "src", 0, "tests/test_demo.py")


def test_run_allowed_command_denies_non_allowlisted_command(tmp_path: Path) -> None:
    init_governed_repo(tmp_path)
    with pytest.raises(PermissionError, match="allowlist"):
        run_allowed_command(tmp_path, load_policy(tmp_path), "ls")


def test_breaking_port_change_requires_approval_and_can_be_approved(tmp_path: Path) -> None:
    init_governed_repo(tmp_path)
    before = (tmp_path / "src" / "api.py").read_text()
    after = (
        "def greet(first, last):\n"
        '    return f"{first} {last}"\n'
    )
    patch = make_patch("src/api.py", before, after)

    stage_patch(tmp_path, "breaking-task", patch)
    task = load_task(tmp_path, "breaking-task")
    task.active_cell_id = "src"
    task.radius = 0
    task.port_check = check_task_ports(tmp_path, task.to_dict(), "src", 0)
    task.proofs = {"checks": [], "artifacts": [], "verification": {"ok": True}}
    save_task(tmp_path, task)

    assert task.port_check["requires_approval"] is True
    assert "breaking port surface change" in task.port_check["approval_reasons"]
    assert task.port_check["proof_tier"] == "elevated"
    assert "pytest -q tests/test_demo.py" in task.port_check["obligations"]["required_checks"]
    assert (
        ".hx/artifacts/breaking-task/port_check.json"
        in task.port_check["obligations"]["required_artifacts"]
    )

    with pytest.raises(RuntimeError, match="human approval required"):
        commit_patch(tmp_path, "breaking-task")

    approval = approve_patch(tmp_path, "breaking-task", "reviewer", "approved breaking change")
    assert approval["human_approved"] is True
    audit_run = load_run(tmp_path, task.audit_run_id)
    assert audit_run.decisions[0]["type"] == "approval"

    task = load_task(tmp_path, "breaking-task")
    task.proofs = collect_task_proofs(tmp_path, load_policy(tmp_path), task.to_dict())
    task.proofs["verification"] = verify_task_proofs(tmp_path, task.to_dict())
    save_task(tmp_path, task)
    artifact_path = tmp_path / ".hx" / "artifacts" / "breaking-task" / "port_check.json"
    assert artifact_path.exists()
    artifact = json.loads(artifact_path.read_text())
    assert artifact["schema_version"] == "hx.governance.v1"
    assert artifact["artifact_kind"] == "port_check"
    assert artifact["task_id"] == "breaking-task"
    assert "compatibility" in artifact
    assert "payload" in artifact

    result = commit_patch(tmp_path, "breaking-task")
    assert result["status"] == "committed"
    assert "def greet(first, last):" in (tmp_path / "src" / "api.py").read_text()
    committed_task = load_task(tmp_path, "breaking-task")
    assert committed_task.metrics["proof_coverage"] == 1.0
    audit_run = load_run(tmp_path, committed_task.audit_run_id)
    assert audit_run.metrics["proof_coverage"] == 1.0


def test_release_mode_high_risk_nonbreaking_change_requires_approval(tmp_path: Path) -> None:
    init_governed_repo(tmp_path, mode="release")
    for index in range(10):
        categories = (
            ["add_export"]
            if index % 2 == 0
            else ["change_invariant", "change_tests_required"]
        )
        record_port_change(
            tmp_path,
            f"history-{index}",
            [{"port_id": "src-tests", "categories": categories}],
            success=False,
        )

    before = (tmp_path / "src" / "api.py").read_text()
    after = (
        before
        + "\n"
        + "def salute(name):\n"
        + '    return f"hi {name}"\n'
    )
    patch = make_patch("src/api.py", before, after)

    stage_patch(tmp_path, "release-task", patch)
    task = load_task(tmp_path, "release-task")
    task.active_cell_id = "src"
    task.radius = 0
    task.port_check = check_task_ports(tmp_path, task.to_dict(), "src", 0)
    task.proofs = {"checks": [], "artifacts": [], "verification": {"ok": True}}
    save_task(tmp_path, task)

    assert task.port_check["classification"] == "compatible"
    assert task.port_check["proof_tier"] == "strict"
    assert task.port_check["requires_approval"] is True
    assert "release mode high-risk port change" in task.port_check["approval_reasons"]
    assert task.port_check["risk_summary"]["max_policy_risk_score"] >= 2.5
    assert (
        ".hx/artifacts/release-task/risk_report.json"
        in task.port_check["obligations"]["required_artifacts"]
    )

    with pytest.raises(RuntimeError, match="human approval required"):
        commit_patch(tmp_path, "release-task")

    task = load_task(tmp_path, "release-task")
    task.proofs = collect_task_proofs(tmp_path, load_policy(tmp_path), task.to_dict())
    save_task(tmp_path, task)
    artifact = json.loads(
        (tmp_path / ".hx" / "artifacts" / "release-task" / "risk_report.json").read_text()
    )
    assert artifact["artifact_kind"] == "risk_report"
    assert artifact["payload"]["max_policy_risk_score"] >= 2.5


def test_commit_patch_requires_proof_verification(tmp_path: Path) -> None:
    init_governed_repo(tmp_path)
    before = (tmp_path / "src" / "api.py").read_text()
    after = before + "\n"
    patch = make_patch("src/api.py", before, after)

    stage_patch(tmp_path, "proof-task", patch)
    task = load_task(tmp_path, "proof-task")
    task.active_cell_id = "src"
    task.radius = 0
    task.port_check = {
        "requires_approval": False,
        "approval_reasons": [],
        "impacted_ports": [],
        "obligations": {"required_checks": [], "required_artifacts": []},
    }
    task.proofs = {"verification": {"ok": False}}
    save_task(tmp_path, task)

    with pytest.raises(RuntimeError, match="proof obligations"):
        commit_patch(tmp_path, "proof-task")


def test_verify_task_proofs_rejects_malformed_governance_artifact(tmp_path: Path) -> None:
    init_governed_repo(tmp_path)
    before = (tmp_path / "src" / "api.py").read_text()
    after = (
        "def greet(first, last):\n"
        '    return f"{first} {last}"\n'
    )
    patch = make_patch("src/api.py", before, after)

    stage_patch(tmp_path, "artifact-task", patch)
    task = load_task(tmp_path, "artifact-task")
    task.active_cell_id = "src"
    task.radius = 0
    task.port_check = check_task_ports(tmp_path, task.to_dict(), "src", 0)
    task.proofs = collect_task_proofs(tmp_path, load_policy(tmp_path), task.to_dict())
    save_task(tmp_path, task)

    artifact_path = tmp_path / ".hx" / "artifacts" / "artifact-task" / "port_check.json"
    artifact = json.loads(artifact_path.read_text())
    artifact.pop("payload")
    artifact_path.write_text(json.dumps(artifact, indent=2) + "\n")

    verification = verify_task_proofs(tmp_path, load_task(tmp_path, "artifact-task").to_dict())
    assert verification["ok"] is False
    assert verification["artifact_errors"]
    assert (
        "missing payload keys" in verification["artifact_errors"][0]
        or "payload must be an object" in verification["artifact_errors"][0]
    )


def test_commit_patch_rejects_tampering_after_proof_verification(tmp_path: Path) -> None:
    init_governed_repo(tmp_path)
    before = (tmp_path / "src" / "api.py").read_text()
    after = before + "\n"
    patch = make_patch("src/api.py", before, after)

    stage_patch(tmp_path, "tamper-after-verify", patch)
    task = load_task(tmp_path, "tamper-after-verify")
    task.active_cell_id = "src"
    task.radius = 0
    task.port_check = check_task_ports(tmp_path, task.to_dict(), "src", 0)
    task.proofs = collect_task_proofs(tmp_path, load_policy(tmp_path), task.to_dict())
    task.proofs["verification"] = verify_task_proofs(tmp_path, task.to_dict())
    save_task(tmp_path, task)

    patch_path = tmp_path / ".hx" / "tasks" / "tamper-after-verify.patch"
    patch_path.write_text(patch + "\n")

    with pytest.raises(RuntimeError, match="staged patch changed after analysis"):
        commit_patch(tmp_path, "tamper-after-verify")


def test_commit_patch_rejects_tampering_after_port_check(tmp_path: Path) -> None:
    init_governed_repo(tmp_path)
    before = (tmp_path / "src" / "api.py").read_text()
    after = before + "\n"
    patch = make_patch("src/api.py", before, after)

    stage_patch(tmp_path, "tamper-after-check", patch)
    task = load_task(tmp_path, "tamper-after-check")
    task.active_cell_id = "src"
    task.radius = 0
    task.port_check = check_task_ports(tmp_path, task.to_dict(), "src", 0)
    save_task(tmp_path, task)

    patch_path = tmp_path / ".hx" / "tasks" / "tamper-after-check.patch"
    patch_path.write_text(patch + "\n")

    task = load_task(tmp_path, "tamper-after-check")
    task.proofs = collect_task_proofs(tmp_path, load_policy(tmp_path), task.to_dict())
    task.proofs["verification"] = verify_task_proofs(tmp_path, task.to_dict())
    save_task(tmp_path, task)

    with pytest.raises(RuntimeError, match="staged patch changed after analysis"):
        commit_patch(tmp_path, "tamper-after-check")
