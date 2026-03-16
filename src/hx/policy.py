from __future__ import annotations

import fnmatch
import tomllib
from pathlib import Path
from typing import Any

from hx.config import DEFAULT_POLICY


class PolicyError(RuntimeError):
    pass


def load_policy(root: Path) -> dict[str, Any]:
    path = root / DEFAULT_POLICY
    if not path.exists():
        raise PolicyError(f"Missing policy file: {path}")
    return tomllib.loads(path.read_text())


def command_allowed(policy: dict[str, Any], command: str) -> bool:
    prefixes = policy.get("commands", {}).get("allowed_prefixes", [])
    return any(command == prefix or command.startswith(prefix + " ") for prefix in prefixes)


def path_allowed(policy: dict[str, Any], rel_path: str) -> bool:
    sandbox = policy.get("path_sandbox", {})
    denylist = sandbox.get("denylist", [])
    allowlist = sandbox.get("allowlist", [])
    if any(fnmatch.fnmatch(rel_path, pattern) for pattern in denylist):
        return False
    return any(fnmatch.fnmatch(rel_path, pattern) for pattern in allowlist)


def default_radius(policy: dict[str, Any]) -> int:
    return int(policy.get("default_radius_max_auto_approve", 1))


def current_mode(policy: dict[str, Any]) -> str:
    return str(policy.get("mode", "dev"))


def mode_settings(policy: dict[str, Any]) -> dict[str, Any]:
    mode = current_mode(policy)
    return policy.get("modes", {}).get(mode, {})


def require_human_for_breaking(policy: dict[str, Any]) -> bool:
    return bool(mode_settings(policy).get("require_human_for_breaking", True))


def strict_risk_threshold(policy: dict[str, Any]) -> float | None:
    settings = mode_settings(policy)
    value = settings.get("strict_risk_threshold")
    return None if value is None else float(value)
