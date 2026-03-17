from __future__ import annotations

import fnmatch
import re
import tomllib
from pathlib import Path
from typing import Any

from hx.config import DEFAULT_POLICY

SHELL_INJECTION_PATTERN = re.compile(r"[;|&`$]|\$\(|&&|\|\|")

# Dangerous argument patterns: commands that invoke subshells or eval
# Note: -c is intentionally NOT blocked here because it's used
# legitimately (e.g., python3 -c 'print(1)' in benchmarks).
# The prefix allowlist + shell injection regex provide the primary
# defense. This pattern catches explicit subprocess spawning.
DANGEROUS_ARG_PATTERNS = re.compile(
    r"\s--exec\b"       # git --exec, find -exec
    r"|\beval\s"        # eval commands
    r"|\bsh\s+-c\b"     # sh -c (explicit shell invocation)
    r"|\bbash\s+-c\b"   # bash -c
)


class PolicyError(RuntimeError):
    pass


def load_policy(root: Path) -> dict[str, Any]:
    path = root / DEFAULT_POLICY
    if not path.exists():
        raise PolicyError(f"Missing policy file: {path}")
    return tomllib.loads(path.read_text())


def command_allowed(policy: dict[str, Any], command: str) -> bool:
    if SHELL_INJECTION_PATTERN.search(command):
        return False
    if DANGEROUS_ARG_PATTERNS.search(f" {command} "):
        return False
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


def risk_weights(policy: dict[str, Any]) -> dict[str, float]:
    defaults = {"entropy": 0.35, "churn": 0.25, "pressure": 0.25, "failures": 0.15}
    overrides = policy.get("risk_weights", {})
    return {k: float(overrides.get(k, v)) for k, v in defaults.items()}
