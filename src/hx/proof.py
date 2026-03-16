from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

from hx.audit import append_event, update_run
from hx.config import ARTIFACT_DIR
from hx.policy import command_allowed

GOVERNANCE_ARTIFACT_SCHEMA_VERSION = "hx.governance.v1"
GOVERNANCE_ARTIFACT_COMPATIBILITY = (
    "Additive fields are allowed within a schema version; removing or renaming "
    "required fields requires a schema-version bump."
)
GOVERNANCE_ARTIFACT_KINDS = {
    "port_check.json": {
        "artifact_kind": "port_check",
        "required_payload_keys": [
            "classification",
            "impacted_ports",
            "obligations",
            "proof_tier",
            "requires_approval",
            "risk_summary",
        ],
    },
    "surface_diff.json": {
        "artifact_kind": "surface_diff",
        "required_payload_keys": ["diffs"],
    },
    "risk_report.json": {
        "artifact_kind": "risk_report",
        "required_payload_keys": [
            "policy_threshold",
            "ports",
            "high_risk_ports",
            "max_policy_risk_score",
            "reporting_note",
        ],
    },
}


def run_allowed_command(
    root: Path,
    policy: dict[str, Any],
    command: str,
    *,
    cwd: str | None = None,
    timeout_s: int | None = None,
) -> dict[str, Any]:
    if not command_allowed(policy, command):
        raise PermissionError(f"Command denied by policy allowlist: {command}")
    argv = shlex.split(command)
    if argv and argv[0] in {"pytest", "ruff"}:
        argv = [sys.executable, "-m", argv[0], *argv[1:]]
    elif argv and argv[0] in {"python", "python3"}:
        argv = [sys.executable, *argv[1:]]
    limits = policy.get("limits", {})
    max_timeout = int(limits.get("max_timeout_s", 120))
    timeout = min(timeout_s or int(limits.get("default_timeout_s", 30)), max_timeout)
    completed = subprocess.run(
        argv,
        cwd=root / cwd if cwd else root,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    max_output = int(limits.get("max_output_bytes", 50000))
    return {
        "command": command,
        "effective_command": argv,
        "returncode": completed.returncode,
        "stdout": completed.stdout[:max_output],
        "stderr": completed.stderr[:max_output],
        "timeout_s": timeout,
    }


def collect_proofs(
    root: Path,
    policy: dict[str, Any],
    task: dict[str, Any],
    obligations: dict[str, Any],
) -> dict[str, Any]:
    artifact_dir = root / ARTIFACT_DIR / task["task_id"]
    artifact_dir.mkdir(parents=True, exist_ok=True)
    checks = []
    artifacts = []
    for index, check in enumerate(obligations.get("required_checks", [])):
        result = run_allowed_command(root, policy, check)
        artifact_path = artifact_dir / f"check_{index}.json"
        artifact_path.write_text(json.dumps(result, indent=2) + "\n")
        checks.append(result)
        artifacts.append(str(artifact_path.relative_to(root)))
    for required in obligations.get("required_artifacts", []):
        candidate = root / required
        artifacts.append(required)
        if not candidate.exists():
            checks.append(
                {
                    "artifact": required,
                    "returncode": 1,
                    "stdout": "",
                    "stderr": "Missing artifact",
                }
            )
    return {"checks": checks, "artifacts": artifacts}


def verify_proofs(task: dict[str, Any]) -> dict[str, Any]:
    proofs = task.get("proofs", {})
    checks = proofs.get("checks", [])
    obligations = task.get("port_check", {}).get("obligations", {})
    required_checks = obligations.get("required_checks", [])
    required_artifacts = obligations.get("required_artifacts", [])
    proof_artifacts = set(proofs.get("artifacts", []))
    failing_checks = [
        check["command"]
        for check in checks
        if check.get("returncode", 1) != 0 and "command" in check
    ]
    missing_checks = [
        check
        for check in required_checks
        if check not in {item.get("command") for item in checks}
    ]
    missing_artifacts = [
        artifact
        for artifact in required_artifacts
        if artifact not in proof_artifacts
    ]
    return {
        "ok": (
            all(check.get("returncode", 1) == 0 for check in checks)
            and len(checks) >= len(required_checks)
            and not missing_artifacts
        ),
        "missing_obligations": failing_checks + missing_checks + missing_artifacts,
        "artifact_errors": [],
    }


def attach_artifacts(root: Path, run_id: str, artifact_refs: list[str]) -> None:
    append_event(root, run_id, "proof.attach", {"artifact_refs": artifact_refs})


def _governance_artifact(
    artifact_kind: str,
    task_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": GOVERNANCE_ARTIFACT_SCHEMA_VERSION,
        "artifact_kind": artifact_kind,
        "task_id": task_id,
        "compatibility": GOVERNANCE_ARTIFACT_COMPATIBILITY,
        "payload": payload,
    }


def generate_governance_artifacts(root: Path, task: dict[str, Any]) -> list[str]:
    artifact_dir = root / ARTIFACT_DIR / task["task_id"]
    artifact_dir.mkdir(parents=True, exist_ok=True)
    created = []
    port_check = task.get("port_check", {})
    impacted_ports = port_check.get("impacted_ports", [])
    if not impacted_ports:
        return created

    port_check_path = artifact_dir / "port_check.json"
    port_check_path.write_text(
        json.dumps(
            _governance_artifact("port_check", task["task_id"], port_check),
            indent=2,
        )
        + "\n"
    )
    created.append(str(port_check_path.relative_to(root)))

    surface_diff_path = artifact_dir / "surface_diff.json"
    surface_diff_path.write_text(
        json.dumps(
            _governance_artifact(
                "surface_diff",
                task["task_id"],
                {"diffs": impacted_ports},
            ),
            indent=2,
        )
        + "\n"
    )
    created.append(str(surface_diff_path.relative_to(root)))

    if port_check.get("proof_tier") == "strict":
        risk_report_path = artifact_dir / "risk_report.json"
        risk_report_path.write_text(
            json.dumps(
                _governance_artifact(
                    "risk_report",
                    task["task_id"],
                    port_check.get("risk_summary", {}),
                ),
                indent=2,
            )
            + "\n"
        )
        created.append(str(risk_report_path.relative_to(root)))
    return created


def validate_governance_artifact(root: Path, task: dict[str, Any], artifact_ref: str) -> str | None:
    path = root / artifact_ref
    spec = GOVERNANCE_ARTIFACT_KINDS.get(path.name)
    if spec is None or not path.exists():
        return None
    try:
        content = json.loads(path.read_text())
    except json.JSONDecodeError:
        return f"{artifact_ref}: invalid JSON"
    if content.get("schema_version") != GOVERNANCE_ARTIFACT_SCHEMA_VERSION:
        return f"{artifact_ref}: unsupported schema version"
    if content.get("artifact_kind") != spec["artifact_kind"]:
        return f"{artifact_ref}: unexpected artifact kind"
    if content.get("task_id") != task.get("task_id"):
        return f"{artifact_ref}: task_id mismatch"
    if content.get("compatibility") != GOVERNANCE_ARTIFACT_COMPATIBILITY:
        return f"{artifact_ref}: compatibility contract mismatch"
    payload = content.get("payload")
    if not isinstance(payload, dict):
        return f"{artifact_ref}: payload must be an object"
    missing = [
        key
        for key in spec["required_payload_keys"]
        if key not in payload
    ]
    if missing:
        return f"{artifact_ref}: missing payload keys: {', '.join(missing)}"
    return None


def collect_task_proofs(
    root: Path,
    policy: dict[str, Any],
    task: dict[str, Any],
) -> dict[str, Any]:
    generated_artifacts = generate_governance_artifacts(root, task)
    obligations = task.get("port_check", {}).get("obligations", {})
    proofs = collect_proofs(root, policy, task, obligations)
    proofs["artifacts"] = sorted(set(proofs["artifacts"] + generated_artifacts))
    run_id = task.get("audit_run_id")
    if run_id:
        append_event(
            root,
            run_id,
            "proof.collect",
            {"task_id": task["task_id"], "artifacts": proofs["artifacts"]},
        )
        update_run(root, run_id, artifacts=proofs["artifacts"])
    return proofs


def verify_task_proofs(root: Path, task: dict[str, Any]) -> dict[str, Any]:
    verification = verify_proofs(task)
    artifact_errors = []
    for artifact_ref in task.get("proofs", {}).get("artifacts", []):
        error = validate_governance_artifact(root, task, artifact_ref)
        if error is not None:
            artifact_errors.append(error)
    if artifact_errors:
        verification["ok"] = False
        verification["artifact_errors"] = artifact_errors
        verification["missing_obligations"] = (
            verification.get("missing_obligations", []) + artifact_errors
        )
    run_id = task.get("audit_run_id")
    if run_id:
        append_event(
            root,
            run_id,
            "proof.verify",
            {"task_id": task["task_id"], "verification": verification},
        )
    return verification
