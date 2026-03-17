"""Task planner: organize multi-step work across hex cells."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hx.config import STATE_DIR, ensure_hx_dirs
from hx.hexmap import HexMapError, load_hexmap, resolve_cell_id

PLAN_FILE = "task_plan.json"


def _plan_path(root: Path) -> Path:
    ensure_hx_dirs(root)
    return root / STATE_DIR / PLAN_FILE


def create_plan(
    root: Path,
    goal: str,
    steps: list[dict[str, Any]],
) -> dict[str, Any]:
    """Create a multi-step task plan.

    Each step has: description, cell, radius, depends_on (list of step indices).
    The planner validates cell IDs and dependency ordering.
    """
    try:
        hexmap = load_hexmap(root)
    except HexMapError:
        hexmap = None

    validated_steps: list[dict[str, Any]] = []
    for i, step in enumerate(steps):
        cell = step.get("cell")
        if hexmap and cell and not hexmap.has_cell(cell):
            # Try to resolve from a path
            resolved = resolve_cell_id(hexmap, cell) if "/" in cell else None
            if resolved:
                cell = resolved
            else:
                available = [c.cell_id for c in hexmap.cells]
                raise ValueError(
                    f"Step {i}: unknown cell '{step['cell']}'. "
                    f"Available cells: {', '.join(available)}"
                )

        deps = step.get("depends_on", [])
        for dep in deps:
            if dep >= i:
                raise ValueError(
                    f"Step {i}: depends_on step {dep} which "
                    f"hasn't been defined yet (forward dependency)."
                )

        validated_steps.append({
            "index": i,
            "description": step.get("description", f"Step {i}"),
            "cell": cell,
            "radius": step.get("radius", 1),
            "depends_on": deps,
            "status": "pending",
            "audit_run_id": None,
        })

    plan = {
        "goal": goal,
        "steps": validated_steps,
        "current_step": 0,
    }

    _plan_path(root).write_text(json.dumps(plan, indent=2) + "\n")
    return plan


def load_plan(root: Path) -> dict[str, Any] | None:
    """Load the current task plan, if one exists."""
    path = _plan_path(root)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def advance_plan(
    root: Path,
    step_index: int,
    status: str = "completed",
    audit_run_id: str | None = None,
) -> dict[str, Any]:
    """Mark a step as completed and advance to the next pending step."""
    plan = load_plan(root)
    if plan is None:
        raise RuntimeError("No active plan. Create one with `hx plan create`.")

    steps = plan["steps"]
    if step_index >= len(steps):
        raise ValueError(f"Step {step_index} does not exist.")

    steps[step_index]["status"] = status
    if audit_run_id:
        steps[step_index]["audit_run_id"] = audit_run_id

    # Find next pending step whose dependencies are met
    for step in steps:
        if step["status"] != "pending":
            continue
        deps_met = all(
            steps[dep]["status"] == "completed"
            for dep in step["depends_on"]
        )
        if deps_met:
            plan["current_step"] = step["index"]
            break
    else:
        # All steps done or blocked
        all_done = all(s["status"] == "completed" for s in steps)
        plan["current_step"] = -1 if all_done else plan["current_step"]

    _plan_path(root).write_text(json.dumps(plan, indent=2) + "\n")
    return plan


def render_plan(plan: dict[str, Any], *, color: bool = False) -> str:
    """Render the task plan as a readable string."""
    lines: list[str] = []
    lines.append(f"Goal: {plan['goal']}")
    lines.append("")

    for step in plan["steps"]:
        idx = step["index"]
        status = step["status"]
        if status == "completed":
            glyph = "done"
        elif status == "running":
            glyph = " >>>"
        elif idx == plan.get("current_step"):
            glyph = "next"
        else:
            glyph = "    "

        cell_str = f" [{step['cell']}]" if step["cell"] else ""
        deps = step.get("depends_on", [])
        dep_str = f" (after {deps})" if deps else ""
        lines.append(
            f"  [{glyph}] {idx}. {step['description']}"
            f"{cell_str}{dep_str}"
        )

    completed = sum(1 for s in plan["steps"] if s["status"] == "completed")
    total = len(plan["steps"])
    lines.append("")
    lines.append(f"Progress: {completed}/{total}")

    return "\n".join(lines)


# --- Sample prompts for common tasks ---

SAMPLE_PROMPTS: list[dict[str, str]] = [
    {
        "category": "Bug fix",
        "prompt": (
            "Fix the bug in {cell}: {description}. "
            "Read the relevant files, identify the root cause, "
            "write the fix, and add a test that reproduces the bug."
        ),
        "example": (
            "hx run 'Fix the null pointer in src/auth.py line 42. "
            "The login function crashes when email is empty. "
            "Add a test that verifies empty email handling.' "
            "--cell src"
        ),
    },
    {
        "category": "Add tests",
        "prompt": (
            "Add unit tests for {cell}. Focus on edge cases "
            "and error paths. Use the existing test patterns."
        ),
        "example": (
            "hx run 'Add unit tests for the payment processing "
            "module. Cover: empty cart, invalid card, timeout, "
            "and successful checkout.' --cell src"
        ),
    },
    {
        "category": "Refactor",
        "prompt": (
            "Refactor {function} in {cell}. Extract the {concern} "
            "into a separate function. Keep all existing tests passing."
        ),
        "example": (
            "hx run 'Refactor the handle_request function in "
            "src/api.py. Extract validation logic into "
            "validate_request(). Keep all tests passing.' --cell src"
        ),
    },
    {
        "category": "Documentation",
        "prompt": (
            "Improve documentation for {cell}. Add docstrings to "
            "public functions and update the README section."
        ),
        "example": (
            "hx run 'Add docstrings to all public functions in "
            "src/utils.py. Include parameter types, return values, "
            "and usage examples.' --cell src"
        ),
    },
    {
        "category": "New feature",
        "prompt": (
            "Add {feature} to {cell}. Implement the core logic, "
            "add tests, and update any relevant documentation."
        ),
        "example": (
            "hx run 'Add rate limiting to the API endpoints. "
            "Use a sliding window algorithm, configure via "
            "POLICY.toml, add tests for limit exceeded and "
            "normal flow.' --cell src --radius 1"
        ),
    },
    {
        "category": "Multi-step (use hx plan)",
        "prompt": "For complex work, create a plan first:",
        "example": (
            "hx plan create 'Migrate auth to OAuth2' \\\n"
            "  --step 'Add OAuth2 client library' --cell src \\\n"
            "  --step 'Update login endpoint' --cell src \\\n"
            "  --step 'Add OAuth2 tests' --cell tests --after 0,1 \\\n"
            "  --step 'Update API docs' --cell docs --after 1"
        ),
    },
]


def render_samples(*, color: bool = False) -> str:
    """Render sample prompts as a readable guide."""
    lines: list[str] = []
    lines.append("Sample task prompts for hx run:")
    lines.append("")

    for sample in SAMPLE_PROMPTS:
        lines.append(f"  {sample['category']}:")
        lines.append(f"    $ {sample['example']}")
        lines.append("")

    lines.append("Tips:")
    lines.append("  - Be specific: name the file, function, or behavior")
    lines.append("  - Include acceptance criteria: 'add a test that...'")
    lines.append("  - Use --cell to target the right cell")
    lines.append("  - Use --radius 0 for single-cell work (safest)")
    lines.append("  - Use hx suggest for repo-specific recommendations")

    return "\n".join(lines)
