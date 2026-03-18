"""Onboarding assistant — turns a high-level user prompt into a governed project.

When a user says "build an app that manages recipes" or "create a CLI tool
for log analysis", the assistant:
1. Analyzes the prompt to determine project type, language, and components
2. Generates a cell layout (HEXMAP) tailored to the described project
3. Creates a fitted POLICY with appropriate sandbox and command rules
4. Builds a multi-step plan to implement the project
5. Suggests the first governed task to kick things off

This bridges the gap between "I want to build X" and a fully governed
hx workspace ready for agentic development.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hx.config import ensure_hx_dirs
from hx.hexmap import save_hexmap
from hx.models import Cell, HexMap, Port

# --- Project archetypes detected from user prompts ---

ARCHETYPES: dict[str, dict[str, Any]] = {
    "web_app": {
        "keywords": [
            "web app", "webapp", "website", "frontend", "backend",
            "api", "rest", "graphql", "dashboard", "saas",
            "full stack", "fullstack", "full-stack",
        ],
        "cells": [
            {"id": "frontend", "paths": ["src/frontend/**", "src/components/**", "public/**"],
             "summary": "Frontend UI components and pages"},
            {"id": "backend", "paths": ["src/api/**", "src/server/**", "src/routes/**"],
             "summary": "Backend API routes and business logic"},
            {"id": "data", "paths": ["src/models/**", "src/db/**", "migrations/**"],
             "summary": "Data models, database, and migrations"},
            {"id": "config", "paths": ["config/**", "*.toml", "*.yaml", "*.json"],
             "summary": "Configuration and environment settings"},
            {"id": "tests", "paths": ["tests/**", "**/*.test.*", "**/*.spec.*"],
             "summary": "Test suites for all cells"},
        ],
        "neighbors": {
            "frontend": {"backend": 1},
            "backend": {"frontend": 0, "data": 2},
            "data": {"backend": 5},
        },
        "language_hint": "typescript",
        "commands": ["npm", "npx", "node", "pytest", "python3"],
    },
    "cli_tool": {
        "keywords": [
            "cli", "command line", "terminal", "command-line",
            "tool", "utility", "script",
        ],
        "cells": [
            {"id": "cli", "paths": ["src/cli/**", "src/main.*"],
             "summary": "CLI entry point, argument parsing, and commands"},
            {"id": "core", "paths": ["src/core/**", "src/lib/**"],
             "summary": "Core business logic and algorithms"},
            {"id": "io", "paths": ["src/io/**", "src/output/**"],
             "summary": "Input/output, file handling, and formatting"},
            {"id": "tests", "paths": ["tests/**"],
             "summary": "Test suites"},
        ],
        "neighbors": {
            "cli": {"core": 1},
            "core": {"cli": 0, "io": 2},
            "io": {"core": 5},
        },
        "language_hint": "python",
        "commands": ["python", "python3", "pytest", "ruff"],
    },
    "api_service": {
        "keywords": [
            "api", "microservice", "service", "server",
            "endpoint", "rest api", "graphql api",
        ],
        "cells": [
            {"id": "routes", "paths": ["src/routes/**", "src/handlers/**", "src/api/**"],
             "summary": "API route handlers and middleware"},
            {"id": "services", "paths": ["src/services/**", "src/logic/**"],
             "summary": "Business logic and service layer"},
            {"id": "data", "paths": ["src/models/**", "src/db/**", "src/repositories/**"],
             "summary": "Data access layer, models, and repositories"},
            {"id": "auth", "paths": ["src/auth/**", "src/middleware/**"],
             "summary": "Authentication, authorization, and middleware"},
            {"id": "tests", "paths": ["tests/**"],
             "summary": "Test suites"},
        ],
        "neighbors": {
            "routes": {"services": 1, "auth": 4},
            "services": {"routes": 0, "data": 2},
            "data": {"services": 5},
            "auth": {"routes": 3},
        },
        "language_hint": "python",
        "commands": ["python", "python3", "pytest", "ruff", "uvicorn"],
    },
    "library": {
        "keywords": [
            "library", "package", "module", "sdk", "framework",
            "pip", "npm package", "crate",
        ],
        "cells": [
            {"id": "core", "paths": ["src/**"],
             "summary": "Core library implementation"},
            {"id": "tests", "paths": ["tests/**"],
             "summary": "Test suites and fixtures"},
            {"id": "docs", "paths": ["docs/**", "examples/**"],
             "summary": "Documentation and usage examples"},
        ],
        "neighbors": {
            "core": {"tests": 1, "docs": 2},
        },
        "language_hint": "python",
        "commands": ["python", "python3", "pytest", "ruff"],
    },
    "mobile_app": {
        "keywords": [
            "mobile", "ios", "android", "react native",
            "flutter", "app", "phone",
        ],
        "cells": [
            {"id": "screens", "paths": ["src/screens/**", "src/pages/**", "lib/screens/**"],
             "summary": "Screen/page components and navigation"},
            {"id": "components", "paths": ["src/components/**", "lib/widgets/**"],
             "summary": "Reusable UI components and widgets"},
            {"id": "state", "paths": ["src/state/**", "src/store/**", "lib/providers/**"],
             "summary": "State management and data flow"},
            {"id": "services", "paths": ["src/services/**", "src/api/**", "lib/services/**"],
             "summary": "API clients, storage, and platform services"},
            {"id": "tests", "paths": ["tests/**", "__tests__/**"],
             "summary": "Test suites"},
        ],
        "neighbors": {
            "screens": {"components": 1, "state": 2},
            "components": {"screens": 0},
            "state": {"screens": 5, "services": 3},
            "services": {"state": 0},
        },
        "language_hint": "typescript",
        "commands": ["npm", "npx", "node", "flutter", "dart"],
    },
    "data_pipeline": {
        "keywords": [
            "data pipeline", "etl", "data processing",
            "analytics", "ml", "machine learning", "ai model",
        ],
        "cells": [
            {"id": "ingest", "paths": ["src/ingest/**", "src/extract/**"],
             "summary": "Data ingestion and extraction"},
            {"id": "transform", "paths": ["src/transform/**", "src/process/**"],
             "summary": "Data transformation and processing logic"},
            {"id": "output", "paths": ["src/output/**", "src/load/**", "src/export/**"],
             "summary": "Data output, loading, and export"},
            {"id": "models", "paths": ["src/models/**", "notebooks/**"],
             "summary": "ML models and analysis notebooks"},
            {"id": "tests", "paths": ["tests/**"],
             "summary": "Test suites and data fixtures"},
        ],
        "neighbors": {
            "ingest": {"transform": 1},
            "transform": {"ingest": 0, "output": 2, "models": 3},
            "output": {"transform": 5},
            "models": {"transform": 0},
        },
        "language_hint": "python",
        "commands": ["python", "python3", "pytest", "jupyter"],
    },
    "generic": {
        "keywords": [],
        "cells": [
            {"id": "src", "paths": ["src/**"],
             "summary": "Main source code"},
            {"id": "tests", "paths": ["tests/**"],
             "summary": "Test suites"},
            {"id": "docs", "paths": ["docs/**"],
             "summary": "Documentation"},
        ],
        "neighbors": {
            "src": {"tests": 1},
        },
        "language_hint": "python",
        "commands": ["python", "python3", "pytest", "ruff"],
    },
}

# Common language → command mapping
LANG_COMMANDS: dict[str, list[str]] = {
    "python": ["python", "python3", "pytest", "ruff", "pip"],
    "typescript": ["npm", "npx", "node", "jest", "tsc"],
    "javascript": ["npm", "npx", "node", "jest"],
    "go": ["go", "go test"],
    "rust": ["cargo", "cargo test", "cargo build"],
    "java": ["mvn", "gradle", "java", "javac"],
    "kotlin": ["gradle", "kotlin", "kotlinc"],
    "ruby": ["ruby", "bundle", "rake", "rspec"],
    "swift": ["swift", "xcodebuild"],
}


@dataclass
class OnboardResult:
    """Result of running the onboarding assistant."""
    archetype: str
    language: str
    cells: list[dict[str, Any]]
    plan_steps: list[dict[str, Any]]
    files_written: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    first_task: str = ""


def detect_archetype(prompt: str) -> str:
    """Detect the project archetype from a user's natural-language prompt."""
    prompt_lower = prompt.lower()
    scores: dict[str, int] = {}

    for archetype, config in ARCHETYPES.items():
        if archetype == "generic":
            continue
        score = 0
        for kw in config["keywords"]:
            if kw in prompt_lower:
                score += len(kw)  # Longer matches score higher
        if score > 0:
            scores[archetype] = score

    if not scores:
        return "generic"
    return max(scores, key=scores.get)


def detect_language(prompt: str) -> str | None:
    """Try to detect the intended language from the prompt."""
    prompt_lower = prompt.lower()
    lang_keywords = {
        "python": ["python", "django", "flask", "fastapi", "pytest"],
        "typescript": ["typescript", "react", "next.js", "nextjs", "angular", "vue", "svelte"],
        "javascript": ["javascript", "node", "express", "vanilla js"],
        "go": ["golang", " go ", "gin", "fiber"],
        "rust": ["rust", "cargo", "actix", "tokio"],
        "java": ["java", "spring", "maven", "gradle"],
        "kotlin": ["kotlin", "ktor", "android kotlin"],
        "ruby": ["ruby", "rails", "sinatra"],
        "swift": ["swift", "swiftui", "ios swift"],
    }
    for lang, keywords in lang_keywords.items():
        for kw in keywords:
            if kw in prompt_lower:
                return lang
    return None


def _build_hexmap_from_archetype(
    archetype: str, project_description: str,
) -> HexMap:
    """Build a HexMap from an archetype definition."""
    config = ARCHETYPES[archetype]
    cells: list[Cell] = []
    neighbors_map = config.get("neighbors", {})

    for cell_def in config["cells"]:
        cell_id = cell_def["id"]
        neighbor_list: list[str | None] = [None] * 6
        port_list: list[Port | None] = [None] * 6

        if cell_id in neighbors_map:
            for neighbor_id, side in neighbors_map[cell_id].items():
                neighbor_list[side] = neighbor_id
                port_list[side] = Port(
                    port_id=f"{cell_id}:{neighbor_id}:{side}",
                    direction="bidirectional",
                    neighbor_cell_id=neighbor_id,
                )

        cells.append(Cell(
            cell_id=cell_id,
            paths=cell_def["paths"],
            summary=cell_def["summary"],
            invariants=[
                "Changes must not break existing tests.",
                "Cross-cell changes require declared ports.",
            ],
            tests=["pytest -q"] if config["language_hint"] == "python" else ["npm test"],
            neighbors=neighbor_list,
            ports=port_list,
        ))

    return HexMap(
        version="1",
        cells=cells,
        port_types={},
        parent_groups=[],
    )


def _build_policy(
    archetype: str, language: str | None,
) -> str:
    """Generate a POLICY.toml tailored to the archetype and language."""
    config = ARCHETYPES[archetype]
    commands = list(config.get("commands", []))

    # Add language-specific commands
    if language and language in LANG_COMMANDS:
        for cmd in LANG_COMMANDS[language]:
            if cmd not in commands:
                commands.append(cmd)

    # Always include git basics
    for cmd in ["git status", "git diff", "git apply"]:
        if cmd not in commands:
            commands.append(cmd)

    commands_str = "\n".join(f'  "{cmd}",' for cmd in commands)
    cell_paths = []
    for cell_def in config["cells"]:
        cell_paths.extend(cell_def["paths"])
    paths_str = "\n".join(f'  "{p}",' for p in cell_paths)

    return f"""mode = "dev"
audit_log_path = ".hx/audit"
artifact_store_path = ".hx/artifacts"
default_radius_max_auto_approve = 1

[path_sandbox]
allowlist = [
{paths_str}
  "*.md",
  "HEXMAP.json",
  "POLICY.toml",
  ".github/workflows/**",
]
denylist = [".env", ".env.*", "secrets/**", "**/*.pem", "**/*.key"]

[commands]
allowed_prefixes = [
{commands_str}
]

[approval_gates]
breaking_changes = true
dependency_changes = true
touching_config_or_secrets = true
modifying_lockfiles = true

[limits]
default_timeout_s = 30
max_timeout_s = 120
max_output_bytes = 50000
max_concurrency = 2

[modes.dev]
require_human_for_breaking = true

[modes.ci]
require_human_for_breaking = true

[modes.release]
require_human_for_breaking = true
strict_risk_threshold = 0.65

[risk_weights]
entropy = 0.35
churn = 0.25
pressure = 0.25
failures = 0.15
"""


def _build_plan_steps(
    archetype: str, prompt: str,
) -> list[dict[str, Any]]:
    """Generate implementation plan steps from archetype and prompt."""
    config = ARCHETYPES[archetype]
    cells = config["cells"]
    steps: list[dict[str, Any]] = []

    # Step 0: always scaffold first
    steps.append({
        "description": "Create directory structure and initial files",
        "cell": cells[0]["id"],
        "radius": 2,
        "depends_on": [],
    })

    # Core implementation steps — one per non-test cell
    for i, cell_def in enumerate(cells):
        if cell_def["id"] == "tests":
            continue
        steps.append({
            "description": f"Implement {cell_def['summary'].lower()}",
            "cell": cell_def["id"],
            "radius": 1,
            "depends_on": [0],  # Depends on scaffold
        })

    # Integration step
    core_steps = list(range(1, len(steps)))
    steps.append({
        "description": "Wire components together and verify integration",
        "cell": cells[0]["id"],
        "radius": 2,
        "depends_on": core_steps,
    })

    # Test step
    test_cell = next(
        (c["id"] for c in cells if c["id"] == "tests"), cells[0]["id"],
    )
    steps.append({
        "description": "Add tests for all implemented components",
        "cell": test_cell,
        "radius": 2,
        "depends_on": [len(steps) - 1],  # Depends on integration
    })

    return steps


def run_onboard(
    root: Path,
    prompt: str,
    *,
    language: str | None = None,
    force: bool = False,
) -> OnboardResult:
    """Analyze a user prompt and scaffold a governed project.

    Args:
        root: Repository root path.
        prompt: User's project description (e.g., "build a recipe app").
        language: Override detected language.
        force: Overwrite existing files.
    """
    result = OnboardResult(
        archetype="",
        language="",
        cells=[],
        plan_steps=[],
    )

    # Step 1: Detect archetype
    archetype = detect_archetype(prompt)
    result.archetype = archetype

    # Step 2: Detect language
    lang = language or detect_language(prompt)
    if not lang:
        lang = ARCHETYPES[archetype]["language_hint"]
    result.language = lang

    # Step 3: Build HEXMAP
    hexmap = _build_hexmap_from_archetype(archetype, prompt)
    result.cells = [
        {"id": c.cell_id, "paths": c.paths, "summary": c.summary}
        for c in hexmap.cells
    ]

    # Step 4: Build plan
    plan_steps = _build_plan_steps(archetype, prompt)
    result.plan_steps = plan_steps

    # Step 5: Write files
    ensure_hx_dirs(root)

    # HEXMAP
    hexmap_path = root / "HEXMAP.json"
    if not hexmap_path.exists() or force:
        save_hexmap(root, hexmap)
        result.files_written.append("HEXMAP.json")

    # POLICY
    policy_path = root / "POLICY.toml"
    if not policy_path.exists() or force:
        policy_content = _build_policy(archetype, lang)
        policy_path.write_text(policy_content)
        result.files_written.append("POLICY.toml")

    # AGENTS.md
    agents_path = root / "AGENTS.md"
    if not agents_path.exists() or force:
        from hx.templates import agents_template
        agents_path.write_text(agents_template())
        result.files_written.append("AGENTS.md")

    # TOOLS.md
    tools_path = root / "TOOLS.md"
    if not tools_path.exists() or force:
        from hx.templates import tools_template
        tools_path.write_text(tools_template())
        result.files_written.append("TOOLS.md")

    # Create cell directories
    for cell in hexmap.cells:
        for pattern in cell.paths:
            dir_path = pattern.replace("/**", "").replace("/*", "")
            if "/" in dir_path and not dir_path.startswith("*"):
                full_path = root / dir_path
                if not full_path.exists():
                    full_path.mkdir(parents=True, exist_ok=True)
                    # Add .gitkeep so git tracks the directory
                    gitkeep = full_path / ".gitkeep"
                    if not gitkeep.exists():
                        gitkeep.write_text("")

    # Save plan
    plan = {
        "goal": prompt,
        "steps": [
            {
                "index": i,
                "description": s["description"],
                "cell": s["cell"],
                "radius": s["radius"],
                "depends_on": s["depends_on"],
                "status": "pending",
                "audit_run_id": None,
            }
            for i, s in enumerate(plan_steps)
        ],
        "current_step": 0,
    }
    plan_path = root / ".hx" / "state" / "task_plan.json"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(plan, indent=2) + "\n")
    result.files_written.append(".hx/state/task_plan.json")

    # Determine first task
    if plan_steps:
        first = plan_steps[0]
        result.first_task = (
            f"hx run '{first['description']}' "
            f"--cell {first['cell']} --radius {first['radius']}"
        )

    return result


def render_onboard_result(
    result: OnboardResult, *, color: bool = False,
) -> str:
    """Render the onboarding result for terminal display."""
    from hx.ui import paint

    lines: list[str] = []

    if result.errors:
        lines.append(paint("Onboarding failed:", "red", color=color))
        for err in result.errors:
            lines.append(f"  ✗ {err}")
        return "\n".join(lines)

    lines.append("")
    lines.append(paint("  ── hx project assistant ──", "bold", "green", color=color))
    lines.append("")
    lines.append(f"  Project type:  {result.archetype.replace('_', ' ')}")
    lines.append(f"  Language:      {result.language}")
    lines.append("")

    # Cell layout
    lines.append(paint("  Cell layout:", "bold", color=color))
    for cell in result.cells:
        paths = ", ".join(cell["paths"][:2])
        if len(cell["paths"]) > 2:
            paths += ", ..."
        lines.append(f"    ⬡ {cell['id']}: {cell['summary']}")
        lines.append(paint(f"      {paths}", "dim", color=color))
    lines.append("")

    # Plan
    lines.append(paint("  Implementation plan:", "bold", color=color))
    for i, step in enumerate(result.plan_steps):
        marker = "→" if i == 0 else " "
        cell_tag = f" [{step['cell']}]"
        lines.append(f"    {marker} {i + 1}. {step['description']}{cell_tag}")
    lines.append("")

    # Files
    if result.files_written:
        lines.append(paint("  Files written:", "bold", color=color))
        for f in result.files_written:
            lines.append(f"    + {f}")
        lines.append("")

    # First task
    if result.first_task:
        lines.append(paint("  Ready to start:", "bold", color=color))
        lines.append(f"    $ {result.first_task}")
        lines.append("")
        lines.append("  Or run `hx plan show` to review the full plan.")

    lines.append("")
    return "\n".join(lines)
