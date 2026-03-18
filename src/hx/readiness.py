"""Project readiness check — single-command health report."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from hx.config import DEFAULT_HEXMAP, DEFAULT_POLICY, HX_DIR
from hx.hexmap import HexMapError, load_hexmap, validate_hexmap
from hx.metrics import top_risky_ports
from hx.policy import PolicyError, current_mode, load_policy
from hx.setup import detect_primary_language, hexmap_stats
from hx.ui import paint


def check_readiness(root: Path) -> dict[str, Any]:
    """Run all readiness checks and return a structured report."""
    checks: list[dict[str, Any]] = []
    recommendations: list[str] = []

    # 1. Core files
    hexmap_exists = (root / DEFAULT_HEXMAP).exists()
    policy_exists = (root / DEFAULT_POLICY).exists()
    hx_dir_exists = (root / HX_DIR).is_dir()
    agents_exists = (root / "AGENTS.md").exists()
    tools_exists = (root / "TOOLS.md").exists()

    checks.append({
        "name": "scaffold",
        "ok": all([hexmap_exists, policy_exists, hx_dir_exists]),
        "detail": {
            "HEXMAP.json": hexmap_exists,
            "POLICY.toml": policy_exists,
            ".hx/": hx_dir_exists,
            "AGENTS.md": agents_exists,
            "TOOLS.md": tools_exists,
        },
    })
    if not hexmap_exists or not policy_exists:
        recommendations.append("Run `hx setup` to initialize the project.")

    # 2. HEXMAP quality
    hexmap_check: dict[str, Any] = {
        "name": "hexmap",
        "ok": False,
        "detail": {},
    }
    if hexmap_exists:
        try:
            hexmap = load_hexmap(root)
            errors = validate_hexmap(root, hexmap)
            stats = hexmap_stats(hexmap)
            hexmap_check["ok"] = len(errors) == 0
            hexmap_check["detail"] = {
                "cells": stats["cells"],
                "ports": stats["ports"],
                "boundary_crossings": stats["boundary_crossings"],
                "parent_groups": stats["parent_groups"],
                "validation_errors": len(errors),
            }
            if errors:
                hexmap_check["detail"]["errors"] = errors[:5]
                recommendations.append(
                    "Fix HEXMAP validation errors "
                    "(run `hx hex validate` for details)."
                )
            if stats["cells"] == 1:
                recommendations.append(
                    "Consider splitting into multiple cells "
                    "as the codebase grows."
                )
        except HexMapError as exc:
            hexmap_check["detail"]["error"] = str(exc)
    checks.append(hexmap_check)

    # 3. Policy fitness
    policy_check: dict[str, Any] = {
        "name": "policy",
        "ok": False,
        "detail": {},
    }
    if policy_exists:
        try:
            policy = load_policy(root)
            mode = current_mode(policy)
            sandbox = policy.get("path_sandbox", {})
            commands = policy.get("commands", {}).get("allowed_prefixes", [])
            policy_check["ok"] = True
            policy_check["detail"] = {
                "mode": mode,
                "sandbox_allowlist": len(sandbox.get("allowlist", [])),
                "sandbox_denylist": len(sandbox.get("denylist", [])),
                "command_prefixes": len(commands),
            }
        except PolicyError as exc:
            policy_check["detail"]["error"] = str(exc)
    checks.append(policy_check)

    # 4. Git health
    git_ok = False
    git_detail: dict[str, Any] = {}
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=root, capture_output=True, text=True, timeout=5,
        )
        git_ok = result.returncode == 0
        if git_ok:
            result = subprocess.run(
                ["git", "log", "--oneline", "-1"],
                cwd=root, capture_output=True, text=True, timeout=5,
            )
            git_detail["has_commits"] = result.returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    git_detail["is_repo"] = git_ok
    checks.append({"name": "git", "ok": git_ok, "detail": git_detail})
    if not git_ok:
        recommendations.append("Initialize a git repository (`git init`).")

    # 5. Test discovery
    test_check: dict[str, Any] = {
        "name": "tests",
        "ok": False,
        "detail": {},
    }
    test_files = list(root.rglob("test_*.py")) + list(root.rglob("*_test.py"))
    test_files += list(root.rglob("*.test.ts")) + list(root.rglob("*.spec.ts"))
    test_files += list(root.rglob("*_test.go"))
    test_count = len(test_files)
    test_check["ok"] = test_count > 0
    test_check["detail"]["test_files"] = test_count

    # Distribution across cells
    if hexmap_exists:
        try:
            hexmap = load_hexmap(root)
            from hx.hexmap import resolve_cell_id
            cell_test_counts: dict[str, int] = {}
            for tf in test_files:
                try:
                    rel = str(tf.relative_to(root))
                except ValueError:
                    continue
                cell = resolve_cell_id(hexmap, rel)
                if cell:
                    cell_test_counts[cell] = cell_test_counts.get(cell, 0) + 1
            test_check["detail"]["by_cell"] = cell_test_counts
            cells_with_tests = len(cell_test_counts)
            total_cells = len(hexmap.cells)
            test_check["detail"]["cell_coverage"] = (
                f"{cells_with_tests}/{total_cells}"
            )
            if cells_with_tests < total_cells:
                missing = [
                    c.cell_id for c in hexmap.cells
                    if c.cell_id not in cell_test_counts
                ]
                recommendations.append(
                    f"Add tests for cells: {', '.join(missing[:3])}."
                )
        except HexMapError:
            pass

    if test_count == 0:
        recommendations.append("Add test files to validate changes.")
    checks.append(test_check)

    # 6. Governance history
    audit_check: dict[str, Any] = {
        "name": "audit",
        "ok": False,
        "detail": {},
    }
    from hx.audit import list_runs
    try:
        runs = list_runs(root)
        run_count = len(runs)
        failed = sum(1 for r in runs if r.status in {"failed", "error"})
        audit_check["ok"] = run_count > 0
        audit_check["detail"] = {
            "total_runs": run_count,
            "failed_runs": failed,
        }
        if run_count == 0:
            recommendations.append(
                "Run a governed task to populate audit history "
                "(`hx run '<task>'`)."
            )
    except Exception:
        audit_check["detail"]["error"] = "Could not read audit logs"
    checks.append(audit_check)

    # 7. Risk profile
    risk_check: dict[str, Any] = {
        "name": "risk",
        "ok": True,
        "detail": {},
    }
    try:
        risky = top_risky_ports(root, 5)
        risk_check["detail"]["risky_ports"] = len(risky)
        if risky:
            risk_check["detail"]["top"] = [
                {
                    "port_id": p["port_id"],
                    "score": p.get("policy_risk_score", 0),
                }
                for p in risky[:3]
            ]
            max_risk = max(
                p.get("policy_risk_score", 0) for p in risky
            )
            if max_risk > 0.7:
                risk_check["ok"] = False
                recommendations.append(
                    f"High-risk port detected (score={max_risk:.2f}). "
                    "Review boundary contracts."
                )
    except Exception:
        pass
    checks.append(risk_check)

    # 8. Provider configuration
    provider_check: dict[str, Any] = {
        "name": "provider",
        "ok": False,
        "detail": {},
    }
    from hx.wizard import load_provider_config, provider_status
    prov_status = provider_status(root)
    provider_check["detail"]["active_provider"] = prov_status["active_provider"]
    provider_check["detail"]["config_exists"] = prov_status["config_exists"]
    any_key_set = any(p["key_set"] for p in prov_status["providers"])
    provider_check["detail"]["any_key_set"] = any_key_set
    provider_check["ok"] = prov_status["config_exists"] and any_key_set
    if not prov_status["config_exists"]:
        recommendations.append(
            "Run `hx provider setup` to configure an LLM provider."
        )
    elif not any_key_set:
        active = prov_status["active_provider"]
        if active:
            env_key = next(
                p["env_key"] for p in prov_status["providers"]
                if p["provider"] == active
            )
            recommendations.append(
                f"Set {env_key} in your environment to activate the provider."
            )
    checks.append(provider_check)

    # 9. Agent config
    agent_check: dict[str, Any] = {
        "name": "agent_config",
        "ok": False,
        "detail": {},
    }
    claude_md = (root / ".claude" / "CLAUDE.md").exists()
    memory_dir = (root / ".claude" / "memory").is_dir()
    agent_check["ok"] = claude_md
    agent_check["detail"] = {
        ".claude/CLAUDE.md": claude_md,
        ".claude/memory/": memory_dir,
    }
    if not claude_md:
        recommendations.append(
            "Run `hx bootstrap` to generate agent config files."
        )
    checks.append(agent_check)

    # Overall
    passed = sum(1 for c in checks if c["ok"])
    total = len(checks)
    language = detect_primary_language(root)

    return {
        "passed": passed,
        "total": total,
        "ready": passed == total,
        "language": language,
        "checks": checks,
        "recommendations": recommendations,
    }


def render_readiness(report: dict[str, Any], *, color: bool = False) -> str:
    """Render the readiness report as a terminal string."""
    lines: list[str] = []

    header = paint("hx readiness", "bold", "blue", color=color)
    lines.append(header)
    lines.append(paint("─" * 50, "dim", color=color))

    if report.get("language") and report["language"] != "unknown":
        lines.append(f"Language: {report['language']}")
        lines.append("")

    for check in report["checks"]:
        if check["ok"]:
            glyph = paint("✓", "green", color=color)
        else:
            glyph = paint("✗", "red", color=color)
        name = check["name"].replace("_", " ").title()
        lines.append(f"  {glyph} {name}")

        # Show key details inline
        detail = check.get("detail", {})
        if check["name"] == "hexmap" and "cells" in detail:
            lines.append(
                f"    {detail['cells']} cells, "
                f"{detail['ports']} ports, "
                f"{detail['boundary_crossings']} crossings"
            )
            if detail.get("validation_errors", 0) > 0:
                lines.append(
                    paint(
                        f"    {detail['validation_errors']} validation errors",
                        "red", color=color,
                    )
                )
        elif check["name"] == "policy" and "mode" in detail:
            lines.append(f"    mode={detail['mode']}")
        elif check["name"] == "tests":
            tf = detail.get("test_files", 0)
            lines.append(f"    {tf} test files")
            if "cell_coverage" in detail:
                lines.append(
                    f"    cell coverage: {detail['cell_coverage']}"
                )
        elif check["name"] == "provider":
            active = detail.get("active_provider")
            if active:
                lines.append(f"    active: {active}")
            else:
                lines.append("    no provider configured")
        elif check["name"] == "audit":
            total = detail.get("total_runs", 0)
            failed = detail.get("failed_runs", 0)
            lines.append(f"    {total} runs ({failed} failed)")

    lines.append("")
    passed = report["passed"]
    total = report["total"]
    score_color = "green" if report["ready"] else "yellow"
    score = paint(f"{passed}/{total} checks passed", score_color, color=color)
    lines.append(score)

    recs = report.get("recommendations", [])
    if recs:
        lines.append("")
        lines.append(paint("Recommendations:", "bold", color=color))
        for rec in recs:
            lines.append(f"  → {rec}")

    return "\n".join(lines)
