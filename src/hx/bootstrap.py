"""Scaffold agent-ready config files for Claude Code, Codex, etc."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from hx.config import ensure_hx_dirs
from hx.hexmap import HexMapError, load_hexmap
from hx.models import HexMap
from hx.policy import PolicyError, current_mode, load_policy


def generate_claude_md(
    hexmap: HexMap, policy: dict[str, Any],
) -> str:
    """Generate .claude/CLAUDE.md with project-specific instructions."""
    mode = current_mode(policy)
    sandbox = policy.get("path_sandbox", {})
    allowlist = sandbox.get("allowlist", [])
    denylist = sandbox.get("denylist", [])
    commands = policy.get("commands", {}).get("allowed_prefixes", [])

    cell_lines = []
    for cell in hexmap.cells:
        paths = ", ".join(cell.paths)
        cell_lines.append(f"- **{cell.cell_id}**: {cell.summary} ({paths})")

    port_lines = []
    for cell in hexmap.cells:
        for i, port in enumerate(cell.ports):
            if port is not None and port.neighbor_cell_id:
                port_lines.append(
                    f"- {cell.cell_id}[{i}] -> "
                    f"{port.neighbor_cell_id} ({port.direction})"
                )

    cells_section = "\n".join(cell_lines) if cell_lines else "- (single cell)"
    ports_section = (
        "\n".join(port_lines) if port_lines else "- (no ports declared)"
    )

    return f"""# CLAUDE.md

This repository uses **hx** hexagonal governance.
All code changes must go through the hx governance flow.

## Governance Mode

Current mode: **{mode}**

## Cell Map

{cells_section}

## Port Topology

{ports_section}

## Policy Constraints

### Path Sandbox
- Allowed: {', '.join(f'`{p}`' for p in allowlist)}
- Denied: {', '.join(f'`{p}`' for p in denylist)}

### Allowed Commands
{chr(10).join(f'- `{cmd}`' for cmd in commands)}

## Workflow

1. Identify which cell you are working in
2. Keep changes within the active cell and allowed radius
3. Stage patches with `hx` before committing
4. Run port checks if changes cross cell boundaries
5. Collect and verify proofs before final commit
6. Breaking changes require human approval

## Key Files

- `HEXMAP.json` — cell topology and port definitions
- `POLICY.toml` — governance policy and sandbox rules
- `AGENTS.md` — agent behavior rules
- `TOOLS.md` — tool usage golden path
- `.hx/` — internal state (audit logs, artifacts, tasks)
"""


def generate_memory_index() -> str:
    """Generate .claude/memory/MEMORY.md index."""
    return """# Memory Index

- [project-context.md](project-context.md) - Project structure and cell layout
- [governance-rules.md](governance-rules.md) - Governance policy and constraints
"""


def generate_project_context(
    hexmap: HexMap, policy: dict[str, Any], language: str,
) -> str:
    """Generate project context memory file."""
    mode = current_mode(policy)
    cell_list = ", ".join(c.cell_id for c in hexmap.cells)
    parent_list = ", ".join(
        pg.parent_id for pg in hexmap.parent_groups
    ) or "none"

    test_commands = set()
    for cell in hexmap.cells:
        for test in cell.tests:
            test_commands.add(test)
    tests_str = ", ".join(sorted(test_commands)) or "none configured"

    return f"""---
name: project-context
description: Project cell layout, language, and test commands
type: project
---

Primary language: {language}
Governance mode: {mode}
Cells: {cell_list}
Parent groups: {parent_list}
Test commands: {tests_str}

**Why:** This context helps agents understand the repo structure
without re-scanning on every conversation.

**How to apply:** Use cell names when scoping work. Run listed
test commands to validate changes.
"""


def generate_governance_rules(policy: dict[str, Any]) -> str:
    """Generate governance rules memory file."""
    mode = current_mode(policy)
    gates = policy.get("approval_gates", {})
    gate_lines = []
    for gate, enabled in gates.items():
        status = "required" if enabled else "not required"
        gate_lines.append(f"- {gate.replace('_', ' ')}: {status}")
    gates_str = "\n".join(gate_lines) if gate_lines else "- none configured"

    weights = policy.get("risk_weights", {})
    weight_lines = [f"- {k}: {v}" for k, v in weights.items()]
    weights_str = "\n".join(weight_lines) if weight_lines else "- defaults"

    limits = policy.get("limits", {})

    return f"""---
name: governance-rules
description: hx governance policy rules and approval gates
type: project
---

Mode: {mode}
Breaking changes require human approval: yes

## Approval Gates
{gates_str}

## Risk Weights
{weights_str}

## Limits
- Default timeout: {limits.get('default_timeout_s', 30)}s
- Max timeout: {limits.get('max_timeout_s', 120)}s
- Max output: {limits.get('max_output_bytes', 50000)} bytes
- Max concurrency: {limits.get('max_concurrency', 2)}

**Why:** These rules are enforced by hx at commit time. Violating
them will block your commit.

**How to apply:** Check approval gates before staging breaking
changes. Stay within timeout and output limits for shell commands.
"""


def generate_agents_update(
    hexmap: HexMap, policy: dict[str, Any],
) -> str:
    """Generate a Bootstrap Context section for AGENTS.md."""
    mode = current_mode(policy)
    cell_count = len(hexmap.cells)
    port_count = sum(
        1 for c in hexmap.cells
        for p in c.ports if p is not None
    )

    return f"""

## Bootstrap Context

Generated by `hx bootstrap`. This section provides agent-ready
context derived from the current HEXMAP and POLICY.

- Governance mode: {mode}
- Cells: {cell_count}
- Ports: {port_count}
- Parent groups: {len(hexmap.parent_groups)}

### Cell Quick Reference
"""  + "".join(
        f"- **{c.cell_id}**: {c.summary}\n"
        for c in hexmap.cells
    )


def _write_if_missing(
    path: Path, content: str, *, force: bool = False,
) -> bool:
    """Write file if missing. Returns True if written."""
    if path.exists() and not force:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return True


def run_bootstrap(
    root: Path,
    *,
    force: bool = False,
    language: str = "unknown",
) -> dict[str, Any]:
    """Orchestrate bootstrap file generation.

    Returns summary of files written.
    """
    ensure_hx_dirs(root)

    try:
        hexmap = load_hexmap(root)
    except HexMapError:
        return {
            "error": (
                "HEXMAP.json not found. Run `hx setup` first."
            ),
            "files_written": [],
        }

    try:
        policy = load_policy(root)
    except PolicyError:
        return {
            "error": (
                "POLICY.toml not found. Run `hx setup` first."
            ),
            "files_written": [],
        }

    files_written: list[str] = []
    claude_dir = root / ".claude"
    memory_dir = claude_dir / "memory"

    # .claude/CLAUDE.md
    content = generate_claude_md(hexmap, policy)
    if _write_if_missing(claude_dir / "CLAUDE.md", content, force=force):
        files_written.append(".claude/CLAUDE.md")

    # .claude/memory/MEMORY.md
    content = generate_memory_index()
    if _write_if_missing(memory_dir / "MEMORY.md", content, force=force):
        files_written.append(".claude/memory/MEMORY.md")

    # .claude/memory/project-context.md
    content = generate_project_context(hexmap, policy, language)
    if _write_if_missing(
        memory_dir / "project-context.md", content, force=force,
    ):
        files_written.append(".claude/memory/project-context.md")

    # .claude/memory/governance-rules.md
    content = generate_governance_rules(policy)
    if _write_if_missing(
        memory_dir / "governance-rules.md", content, force=force,
    ):
        files_written.append(".claude/memory/governance-rules.md")

    # Update AGENTS.md with bootstrap section
    agents_path = root / "AGENTS.md"
    if agents_path.exists():
        existing = agents_path.read_text()
        marker = "## Bootstrap Context"
        if marker not in existing or force:
            update = generate_agents_update(hexmap, policy)
            if marker in existing:
                # Replace existing bootstrap section
                idx = existing.index(marker)
                existing = existing[:idx].rstrip()
            agents_path.write_text(existing + "\n" + update)
            files_written.append("AGENTS.md")

    return {"files_written": files_written}
