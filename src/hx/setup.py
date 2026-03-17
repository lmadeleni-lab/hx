"""One-command guided onboarding for hx."""
from __future__ import annotations

import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from hx.config import DEFAULT_HEXMAP, DEFAULT_POLICY, ensure_hx_dirs
from hx.hexmap import build_hexmap, save_hexmap, validate_hexmap
from hx.models import HexMap
from hx.templates import (
    agents_template,
    benchmark_template,
    policy_toml,
    starter_hexmap,
    tools_template,
)

LANG_MAP: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".rb": "ruby",
    ".cpp": "cpp",
    ".c": "c",
    ".cs": "csharp",
    ".swift": "swift",
}

SCAN_EXCLUDE = {
    ".git", ".hx", ".github", "__pycache__", ".pytest_cache",
    ".ruff_cache", "node_modules", ".venv", "venv", ".tox",
    "dist", "build", ".mypy_cache", ".eggs", "egg-info",
}


def detect_primary_language(root: Path) -> str:
    """Scan file extensions and return the dominant language."""
    counts: Counter[str] = Counter()
    for path in root.rglob("*"):
        if any(part in SCAN_EXCLUDE for part in path.parts):
            continue
        if path.is_file() and path.suffix in LANG_MAP:
            counts[LANG_MAP[path.suffix]] += 1
    if not counts:
        return "unknown"
    return counts.most_common(1)[0][0]


def suggest_policy_mode(root: Path, hexmap: HexMap) -> str:
    """Suggest a policy mode based on repo characteristics."""
    cell_count = len(hexmap.cells)
    has_ci = (root / ".github" / "workflows").is_dir()
    has_tags = False
    try:
        result = subprocess.run(
            ["git", "tag", "-l"],
            cwd=root, capture_output=True, text=True, timeout=5,
        )
        has_tags = bool(result.stdout.strip())
    except (subprocess.SubprocessError, FileNotFoundError):
        pass

    if has_tags and cell_count > 10:
        return "release"
    if has_ci or cell_count > 20:
        return "ci"
    return "dev"


def hexmap_stats(hexmap: HexMap) -> dict[str, Any]:
    """Compute hexmap topology statistics."""
    port_count = 0
    boundary_crossings = 0
    for cell in hexmap.cells:
        for i, port in enumerate(cell.ports):
            if port is not None:
                port_count += 1
            if cell.neighbors[i] is not None:
                boundary_crossings += 1
    return {
        "cells": len(hexmap.cells),
        "ports": port_count,
        "boundary_crossings": boundary_crossings,
        "parent_groups": len(hexmap.parent_groups),
    }


def _write_if_missing(
    path: Path, content: str, *, force: bool = False,
) -> bool:
    """Write file if it doesn't exist. Returns True if written."""
    if path.exists() and not force:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return True


def run_setup(
    root: Path,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Orchestrate the full setup flow.

    Returns a summary dict with language, stats, suggested mode,
    validation errors, and files written.
    """
    files_written: list[str] = []

    # 1. Create internal directories
    ensure_hx_dirs(root)

    # 2. Detect primary language
    language = detect_primary_language(root)

    # 3. Scaffold template files
    scaffolds = [
        ("AGENTS.md", agents_template()),
        ("TOOLS.md", tools_template()),
        (DEFAULT_POLICY, policy_toml()),
        (DEFAULT_HEXMAP, starter_hexmap()),
        ("BENCHMARK.md", benchmark_template()),
    ]
    for rel_path, content in scaffolds:
        if _write_if_missing(root / rel_path, content, force=force):
            files_written.append(rel_path)

    # 4. Build hexmap from repo structure
    hexmap = build_hexmap(root)
    save_hexmap(root, hexmap)
    if DEFAULT_HEXMAP not in files_written:
        files_written.append(DEFAULT_HEXMAP)

    # 5. Validate
    errors = validate_hexmap(root, hexmap)

    # 6. Compute stats
    stats = hexmap_stats(hexmap)

    # 7. Suggest policy mode
    suggested_mode = suggest_policy_mode(root, hexmap)

    return {
        "language": language,
        "stats": stats,
        "suggested_mode": suggested_mode,
        "validation_errors": errors,
        "files_written": files_written,
    }
