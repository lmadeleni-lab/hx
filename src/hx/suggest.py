"""First-task scaffolding — suggest and create low-risk starter tasks."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from hx.hexmap import HexMapError, load_hexmap, resolve_cell_id
from hx.metrics import top_risky_ports


def _count_test_files(root: Path, cell_paths: list[str]) -> int:
    """Count test files matching cell path patterns."""
    count = 0
    for pattern in cell_paths:
        base = pattern.replace("/**", "")
        cell_dir = root / base
        if cell_dir.is_dir():
            count += len(list(cell_dir.rglob("test_*.py")))
            count += len(list(cell_dir.rglob("*_test.py")))
            count += len(list(cell_dir.rglob("*.test.ts")))
            count += len(list(cell_dir.rglob("*_test.go")))
    return count


def _find_lint_issues(root: Path) -> list[dict[str, str]]:
    """Try to find lint issues for suggestion."""
    issues: list[dict[str, str]] = []
    try:
        result = subprocess.run(
            ["ruff", "check", "--select", "F", "--quiet", "."],
            cwd=root, capture_output=True, text=True, timeout=15,
        )
        for line in result.stdout.strip().split("\n")[:3]:
            if line.strip():
                issues.append({"type": "lint", "detail": line.strip()})
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    return issues


def suggest_tasks(root: Path) -> list[dict[str, Any]]:
    """Analyze the repo and suggest low-risk starter tasks.

    Returns a list of task suggestions sorted by safety (safest first).
    """
    suggestions: list[dict[str, Any]] = []

    try:
        hexmap = load_hexmap(root)
    except HexMapError:
        return [
            {
                "task": "Initialize hx governance",
                "command": "hx setup",
                "risk": "none",
                "cell": None,
                "reason": "Project not yet initialized with hx.",
            }
        ]

    # 1. Cells with no tests
    for cell in hexmap.cells:
        test_count = _count_test_files(root, cell.paths)
        if test_count == 0:
            suggestions.append({
                "task": f"Add tests for cell '{cell.cell_id}'",
                "command": (
                    f"hx run 'Add unit tests for the {cell.cell_id} cell' "
                    f"--cell {cell.cell_id}"
                ),
                "risk": "low",
                "cell": cell.cell_id,
                "reason": (
                    f"Cell '{cell.cell_id}' has no test files. "
                    "Adding tests is safe and improves governance."
                ),
            })

    # 2. Lint issues
    lint_issues = _find_lint_issues(root)
    if lint_issues:
        # Find which cell the first issue is in
        first = lint_issues[0]["detail"]
        parts = first.split(":")
        cell_id = None
        if len(parts) >= 1:
            cell_id = resolve_cell_id(hexmap, parts[0])
        suggestions.append({
            "task": "Fix lint warnings",
            "command": (
                f"hx run 'Fix lint warnings in {cell_id or 'the project'}'"
                + (f" --cell {cell_id}" if cell_id else "")
            ),
            "risk": "low",
            "cell": cell_id,
            "reason": f"Found {len(lint_issues)} lint issue(s).",
        })

    # 3. Cells with missing summaries
    for cell in hexmap.cells:
        if cell.summary.startswith("Auto-discovered") or not cell.summary:
            suggestions.append({
                "task": f"Document cell '{cell.cell_id}'",
                "command": (
                    f"hx run 'Improve the summary and invariants "
                    f"for cell {cell.cell_id}' --cell {cell.cell_id}"
                ),
                "risk": "low",
                "cell": cell.cell_id,
                "reason": (
                    f"Cell '{cell.cell_id}' has a generic summary. "
                    "Better docs improve agent effectiveness."
                ),
            })

    # 4. Risky ports to review
    try:
        risky = top_risky_ports(root, 3)
        for port in risky:
            score = port.get("policy_risk_score", 0)
            if score > 0.3:
                suggestions.append({
                    "task": f"Review risky port '{port['port_id']}'",
                    "command": (
                        "hx run 'Review and improve contracts for "
                        f"port {port['port_id']}'"
                    ),
                    "risk": "medium",
                    "cell": None,
                    "reason": (
                        f"Port '{port['port_id']}' has risk score "
                        f"{score:.2f}."
                    ),
                })
    except Exception:
        pass

    # 5. Missing .claude/ config
    if not (root / ".claude" / "CLAUDE.md").exists():
        suggestions.append({
            "task": "Bootstrap agent configuration",
            "command": "hx bootstrap",
            "risk": "none",
            "cell": None,
            "reason": (
                "No .claude/CLAUDE.md found. Bootstrap generates "
                "agent-ready config derived from your HEXMAP and POLICY."
            ),
        })

    # 6. Empty invariants
    for cell in hexmap.cells:
        if not cell.invariants:
            suggestions.append({
                "task": f"Define invariants for cell '{cell.cell_id}'",
                "command": (
                    f"hx run 'Define invariants for cell "
                    f"{cell.cell_id}' --cell {cell.cell_id}"
                ),
                "risk": "low",
                "cell": cell.cell_id,
                "reason": (
                    f"Cell '{cell.cell_id}' has no invariants. "
                    "Invariants guide agents and improve governance."
                ),
            })

    # Sort: none < low < medium < high
    risk_order = {"none": 0, "low": 1, "medium": 2, "high": 3}
    suggestions.sort(key=lambda s: risk_order.get(s["risk"], 99))

    return suggestions
