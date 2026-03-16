from __future__ import annotations

from pathlib import Path

HX_DIR = ".hx"
AUDIT_DIR = ".hx/audit"
ARTIFACT_DIR = ".hx/artifacts"
TASK_DIR = ".hx/tasks"
STATE_DIR = ".hx/state"
DEFAULT_HEXMAP = "HEXMAP.json"
DEFAULT_POLICY = "POLICY.toml"


def ensure_hx_dirs(root: Path) -> None:
    for rel in (HX_DIR, AUDIT_DIR, ARTIFACT_DIR, TASK_DIR, STATE_DIR):
        (root / rel).mkdir(parents=True, exist_ok=True)


def repo_root(cwd: str | Path | None = None) -> Path:
    return Path(cwd or ".").resolve()
