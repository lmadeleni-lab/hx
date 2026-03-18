from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from hx import __version__
from hx.audit import list_runs
from hx.benchmark import (
    load_task_battery,
    report_benchmark,
    run_benchmark,
    validate_task_battery,
)
from hx.codex_integration import codex_status, install_codex_config
from hx.config import DEFAULT_HEXMAP, DEFAULT_POLICY, ensure_hx_dirs, repo_root
from hx.hexmap import build_hexmap, load_hexmap, save_hexmap, validate_hexmap
from hx.memory import memory_status, resume_context, summarize_memory
from hx.metrics import summarize_runs, top_risky_ports
from hx.parents import parent_groups_overview, parent_summary, resolve_parent_group
from hx.templates import (
    agents_template,
    benchmark_template,
    policy_toml,
    starter_hexmap,
    tools_template,
)
from hx.ui import (
    TerminalUI,
    clear_screen,
    render_action_card,
    render_hex_view,
    render_parent_view,
    render_parent_watch_dashboard,
    render_watch_dashboard,
    should_use_color,
)
from hx.ui import (
    render_startup_screen as render_terminal_startup_screen,
)


class HxArgumentParser(argparse.ArgumentParser):
    def print_help(self, file=None) -> None:
        stream = file or sys.stdout
        if self.prog == "hx" and should_show_startup_screen(stream):
            print(
                render_terminal_startup_screen(__version__, color=should_use_color(stream)),
                file=stream,
            )
        super().print_help(file)


def write_if_missing(path: Path, content: str, *, force: bool = False) -> None:
    if path.exists() and not force:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def should_show_startup_screen(stream) -> bool:
    if os.environ.get("HX_NO_BANNER", "").lower() in {"1", "true", "yes"}:
        return False
    if sys.platform != "darwin":
        return False
    isatty = getattr(stream, "isatty", None)
    return bool(isatty and isatty())


def render_startup_screen() -> str:
    return render_terminal_startup_screen(__version__, color=False)


def doctor_problems(root: Path) -> list[str]:
    problems = []
    if sys.platform != "darwin":
        problems.append("hx currently supports macOS terminal workflows only")
    if shutil.which("python3") is None:
        problems.append("Missing python3; install Python 3.11+ and retry")
    if shutil.which("git") is None:
        problems.append(
            "Missing git; install Xcode Command Line Tools with `xcode-select --install`"
        )
    if not (root / DEFAULT_POLICY).exists():
        problems.append("Missing POLICY.toml")
    if not (root / DEFAULT_HEXMAP).exists():
        problems.append("Missing HEXMAP.json")
    return problems


def cmd_init(args: argparse.Namespace) -> int:
    root = repo_root(args.root)
    ui = TerminalUI(mode=args.ui_mode)
    with ui.activity(
        "Initializing hx workspace",
        success_message="Initialized hx workspace",
    ) as activity:
        activity.update("Creating internal directories")
        ensure_hx_dirs(root)
        activity.update("Writing AGENTS.md")
        write_if_missing(root / "AGENTS.md", agents_template(), force=args.force)
        activity.update("Writing TOOLS.md")
        write_if_missing(root / "TOOLS.md", tools_template(), force=args.force)
        activity.update("Writing POLICY.toml")
        write_if_missing(root / DEFAULT_POLICY, policy_toml(), force=args.force)
        activity.update("Writing HEXMAP.json")
        write_if_missing(root / DEFAULT_HEXMAP, starter_hexmap(), force=args.force)
        activity.update("Writing BENCHMARK.md")
        write_if_missing(root / "BENCHMARK.md", benchmark_template(), force=args.force)
    print(f"Initialized hx templates in {root}")
    print(
        render_action_card(
            "First Run Flow",
            [
                "hx codex setup",
                "codex --login",
                "codex",
            ],
            color=ui.color,
        )
    )
    return 0


def cmd_hex_build(args: argparse.Namespace) -> int:
    root = repo_root(args.root)
    ui = TerminalUI(mode=args.ui_mode)
    with ui.activity(
        "Building HEXMAP topology",
        success_message="Built HEXMAP topology",
    ) as activity:
        activity.update("Scanning repository paths")
        hexmap = build_hexmap(root)
        activity.update("Writing HEXMAP.json")
        save_hexmap(root, hexmap)
    print(f"Wrote {DEFAULT_HEXMAP}")
    return 0


def cmd_hex_validate(args: argparse.Namespace) -> int:
    root = repo_root(args.root)
    ui = TerminalUI(mode=args.ui_mode)
    with ui.activity(
        "Validating HEXMAP topology",
        success_message="Validated HEXMAP topology",
    ) as activity:
        activity.update("Loading HEXMAP.json")
        all_issues = validate_hexmap(root, load_hexmap(root))
        warnings = [e for e in all_issues if e.startswith("warning:")]
        errors = [e for e in all_issues if not e.startswith("warning:")]
        if errors:
            activity.fail("HEXMAP validation failed")
            for error in errors:
                print(error)
        if warnings:
            for w in warnings:
                print(w)
        if errors:
            return 1
    if not errors:
        print("HEXMAP.json is valid")
    return 0


def cmd_hex_show(args: argparse.Namespace) -> int:
    root = repo_root(args.root)
    ui = TerminalUI(mode=args.ui_mode)
    with ui.activity(
        "Rendering hex neighborhood",
        success_message="Rendered hex neighborhood",
    ):
        hexmap = load_hexmap(root)
        if args.json:
            payload: dict[str, object] = {
                "cell_id": args.cell_id,
                "radius": args.radius,
                "view": render_hex_view(
                    hexmap,
                    args.cell_id,
                    args.radius,
                    color=False,
                ),
            }
            if args.include_parent:
                payload["parent"] = resolve_parent_group(hexmap, args.cell_id)
        else:
            payload = render_hex_view(
                hexmap,
                args.cell_id,
                args.radius,
                color=ui.color,
            )
            if args.include_parent:
                parent_info = resolve_parent_group(hexmap, args.cell_id)
                if parent_info is not None:
                    payload += (
                        "\n\nParent membership:\n"
                        f"- parent_id: {parent_info['parent_id']}\n"
                        f"- center_cell_id: {parent_info['center_cell_id']}\n"
                        f"- slot: {parent_info['slot']}"
                    )
    print(json.dumps(payload, indent=2) if args.json else payload)
    return 0


def cmd_hex_watch(args: argparse.Namespace) -> int:
    root = repo_root(args.root)
    ui = TerminalUI(mode=args.ui_mode)
    tick = 0
    iterations = args.iterations
    try:
        while True:
            tick += 1
            hexmap = load_hexmap(root)
            runs = list(reversed(list_runs(root)))
            parent_details = None
            parent_info = resolve_parent_group(hexmap, args.cell_id)
            if parent_info is not None:
                parent_details = parent_summary(root, hexmap, parent_info["parent_id"])
            frame = render_watch_dashboard(
                hexmap,
                args.cell_id,
                args.radius,
                runs,
                tick=tick,
                interval_s=args.interval,
                parent_details=parent_details,
                color=ui.color,
            )
            clear_screen(sys.stdout)
            print(frame, end="" if frame.endswith("\n") else "\n")
            if iterations and tick >= iterations:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        ui.note("Stopped hex watch", level="warning")
    return 0


def cmd_hex_parent_show(args: argparse.Namespace) -> int:
    root = repo_root(args.root)
    ui = TerminalUI(mode=args.ui_mode)
    with ui.activity(
        "Rendering parent neighborhood",
        success_message="Rendered parent neighborhood",
    ):
        hexmap = load_hexmap(root)
        if args.json:
            payload = parent_summary(root, hexmap, args.parent_id)
        else:
            payload = render_parent_view(hexmap, args.parent_id, color=ui.color)
    print(json.dumps(payload, indent=2) if args.json else payload)
    return 0


def cmd_hex_parent_watch(args: argparse.Namespace) -> int:
    root = repo_root(args.root)
    ui = TerminalUI(mode=args.ui_mode)
    tick = 0
    iterations = args.iterations
    try:
        while True:
            tick += 1
            hexmap = load_hexmap(root)
            runs = list(reversed(list_runs(root)))
            frame = render_parent_watch_dashboard(
                hexmap,
                root,
                args.parent_id,
                runs,
                tick=tick,
                interval_s=args.interval,
                color=ui.color,
            )
            clear_screen(sys.stdout)
            print(frame, end="" if frame.endswith("\n") else "\n")
            if iterations and tick >= iterations:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        ui.note("Stopped parent watch", level="warning")
    return 0


def cmd_hex_parent_summarize(args: argparse.Namespace) -> int:
    root = repo_root(args.root)
    ui = TerminalUI(mode=args.ui_mode)
    with ui.activity(
        "Summarizing parent group",
        success_message="Summarized parent group",
    ):
        hexmap = load_hexmap(root)
        payload = parent_summary(root, hexmap, args.parent_id)
    print(json.dumps(payload, indent=2))
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    root = repo_root(args.root)
    ui = TerminalUI(mode=args.ui_mode)
    with ui.activity(
        "Running environment checks",
        success_message="Environment checks complete",
    ) as activity:
        activity.update("Checking host prerequisites")
        problems = doctor_problems(root)
        activity.update("Checking git repository state")
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=root,
            capture_output=True,
        )
        if result.returncode != 0:
            problems.append("Not inside a git repository; staged patch commit flow needs git apply")
        if problems:
            activity.fail("Environment checks found blocking issues")
            for problem in problems:
                print(problem)
            return 1
    print("hx doctor found no blocking issues")
    print("Supported runtime: macOS terminal")
    print("Prerequisites detected: python3, git")
    status = codex_status()
    if status.codex_installed:
        print("Codex CLI detected")
        print(
            "Codex MCP config: "
            + ("present for hx" if status.hx_configured else f"missing in {status.config_path}")
        )
    else:
        print("Codex CLI not detected; install Codex CLI before `hx codex setup`")
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    root = repo_root(args.root)
    ui = TerminalUI(mode=args.ui_mode)
    from hx.onboard import render_onboard_result, run_onboard

    prompt = args.prompt
    language = getattr(args, "language", None)
    force = getattr(args, "force", False)

    with ui.activity(
        "Analyzing project requirements",
        success_message="Project scaffolded",
    ):
        result = run_onboard(root, prompt, language=language, force=force)

    print(render_onboard_result(result, color=ui.color))
    return 0 if not result.errors else 1


def cmd_provider_setup(args: argparse.Namespace) -> int:
    root = repo_root(args.root)
    ui = TerminalUI(mode=args.ui_mode)
    from hx.wizard import render_wizard_result, run_wizard

    provider = getattr(args, "provider_name", None)
    non_interactive = getattr(args, "non_interactive", False)
    skip_validation = getattr(args, "skip_validation", False)

    result = run_wizard(
        root,
        provider=provider,
        non_interactive=non_interactive,
        skip_validation=skip_validation,
    )
    print(render_wizard_result(result, color=ui.color))
    return 0 if not result.errors else 1


def cmd_provider_status(args: argparse.Namespace) -> int:
    root = repo_root(args.root)
    ui = TerminalUI(mode=args.ui_mode)
    from hx.wizard import provider_status, render_provider_status

    status = provider_status(root)
    if getattr(args, "json", False):
        print(json.dumps(status, indent=2))
    else:
        print(render_provider_status(status, color=ui.color))
    return 0


def cmd_codex_setup(args: argparse.Namespace) -> int:
    root = repo_root(args.root)
    ui = TerminalUI(mode=args.ui_mode)
    with ui.activity(
        "Configuring Codex MCP integration",
        success_message="Configured Codex MCP integration",
    ) as activity:
        activity.update("Writing ~/.codex/config.toml entry for hx")
        status = install_codex_config(root)
        if not status.codex_installed:
            activity.note(
                "Codex CLI was not found on PATH; config was written anyway",
                level="warning",
            )
    print(f"Wrote Codex config in {status.config_path}")
    print(f"Configured hx command: {status.hx_command}")
    print(
        render_action_card(
            "Codex Connection Flow",
            [
                "Run `codex --login` if you have not signed in yet",
                "Run `codex` from this repository",
                "Let Codex spawn hx automatically through MCP",
            ],
            color=ui.color,
        )
    )
    print("Do not keep `hx mcp serve --transport stdio` running manually when using Codex.")
    return 0


def cmd_codex_status(args: argparse.Namespace) -> int:
    ui = TerminalUI(mode=args.ui_mode)
    with ui.activity(
        "Inspecting Codex integration state",
        success_message="Inspected Codex integration state",
    ):
        status = codex_status()
    payload = {
        "codex_installed": status.codex_installed,
        "config_path": str(status.config_path),
        "hx_command": status.hx_command,
        "hx_configured": status.hx_configured,
    }
    print(json.dumps(payload, indent=2))
    if not status.codex_installed:
        print("Next: install Codex CLI, then run `hx codex setup`.")
    elif not status.hx_configured:
        print("Next: run `hx codex setup`.")
    else:
        print("Next: run `codex --login` if needed, then launch `codex` in this repo.")
    return 0


def cmd_gemini_setup(args: argparse.Namespace) -> int:
    root = repo_root(args.root)
    ui = TerminalUI(mode=args.ui_mode)
    from hx.gemini_integration import install_gemini_config
    with ui.activity(
        "Configuring Gemini MCP integration",
        success_message="Configured Gemini MCP integration",
    ) as activity:
        activity.update("Writing Gemini settings entry for hx")
        status = install_gemini_config(root)
        if not status.gemini_installed:
            activity.note(
                "Gemini CLI not found on PATH; config written anyway",
                level="warning",
            )
    print(f"Wrote Gemini config in {status.config_path}")
    print(
        render_action_card(
            "Gemini Connection Flow",
            [
                "Run `gemini` from this repository",
                "hx MCP server will be available automatically",
                "Use hex.context, repo.read, port.check tools",
            ],
            color=ui.color,
        )
    )
    return 0


def cmd_gemini_status(args: argparse.Namespace) -> int:
    ui = TerminalUI(mode=args.ui_mode)
    from hx.gemini_integration import gemini_status
    with ui.activity(
        "Inspecting Gemini integration state",
        success_message="Inspected Gemini integration state",
    ):
        status = gemini_status()
    payload = {
        "gemini_installed": status.gemini_installed,
        "config_path": str(status.config_path),
        "hx_command": status.hx_command,
        "hx_configured": status.hx_configured,
    }
    print(json.dumps(payload, indent=2))
    if not status.gemini_installed:
        print("Next: install Gemini CLI, then run `hx gemini setup`.")
    elif not status.hx_configured:
        print("Next: run `hx gemini setup`.")
    else:
        print("Next: launch `gemini` in this repo.")
    return 0


def cmd_memory_summarize(args: argparse.Namespace) -> int:
    root = repo_root(args.root)
    ui = TerminalUI(mode=args.ui_mode)
    with ui.activity(
        "Compacting repo context into state summaries",
        success_message="Compacted repo context into state summaries",
    ):
        payload = summarize_memory(root)
    print(json.dumps(payload if args.json else payload["repo_summary"], indent=2))
    return 0


def cmd_memory_status(args: argparse.Namespace) -> int:
    root = repo_root(args.root)
    ui = TerminalUI(mode=args.ui_mode)
    with ui.activity(
        "Inspecting memory state",
        success_message="Inspected memory state",
    ):
        payload = memory_status(root)
    print(json.dumps(payload, indent=2))
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    root = repo_root(args.root)
    ui = TerminalUI(mode=args.ui_mode)
    with ui.activity(
        "Loading resume context",
        success_message="Loaded resume context",
    ):
        payload = resume_context(root)
    print(json.dumps(payload, indent=2))
    return 0


def cmd_log(args: argparse.Namespace) -> int:
    root = repo_root(args.root)
    ui = TerminalUI(mode=args.ui_mode)
    with ui.activity("Loading audit summary", success_message="Loaded audit summary"):
        summary = summarize_runs(root)
        risky = top_risky_ports(root, args.n)
        parent_risky = parent_groups_overview(root, load_hexmap(root))
        parent_risky = sorted(
            parent_risky,
            key=lambda item: item["metrics"]["parent_architecture_potential"],
            reverse=True,
        )[: args.n]
    print(json.dumps(summary, indent=2))
    if risky:
        print("")
        print("Top risky ports:")
        for item in risky:
            print(
                f"- {item['port_id']}: policy_risk={item['policy_risk_score']} "
                f"entropy={item['entropy']} churn={item['churn']} "
                f"pressure={item['pressure']}"
            )
    if parent_risky:
        print("")
        print("Top risky parents:")
        for item in parent_risky:
            metrics = item["metrics"]
            print(
                f"- {item['parent_id']}: potential={metrics['parent_architecture_potential']} "
                f"pressure={metrics['parent_boundary_pressure']} "
                f"cohesion={metrics['parent_cohesion']}"
            )
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    from hx.replay import replay_run

    root = repo_root(args.root)
    ui = TerminalUI(mode=args.ui_mode)
    with ui.activity(
        f"Replaying audit run {args.audit_run_id}",
        success_message=f"Replayed audit run {args.audit_run_id}",
    ):
        result = replay_run(root, args.audit_run_id)
    print(json.dumps(result, indent=2))
    return 0


def cmd_setup(args: argparse.Namespace) -> int:
    root = repo_root(args.root)
    ui = TerminalUI(mode=args.ui_mode)

    from hx.setup import run_setup

    with ui.activity(
        "Running guided setup",
        success_message="Setup complete",
    ) as activity:
        activity.update("Detecting language and scanning repo")
        result = run_setup(root, force=args.force)

    stats = result["stats"]
    print(f"Language detected: {result['language']}")
    print(
        f"Hexmap: {stats['cells']} cells, "
        f"{stats['ports']} ports, "
        f"{stats['boundary_crossings']} boundary crossings, "
        f"{stats['parent_groups']} parent groups"
    )
    print(f"Suggested policy mode: {result['suggested_mode']}")

    if result["validation_errors"]:
        print(f"\nValidation warnings ({len(result['validation_errors'])}):")
        for err in result["validation_errors"][:5]:
            print(f"  - {err}")

    print(f"\nFiles written: {', '.join(result['files_written'])}")
    print(
        render_action_card(
            "Next Steps",
            [
                "hx bootstrap    — scaffold agent config (.claude/)",
                "hx status        — view governance dashboard",
                "hx run '<task>'  — run a governed agent task",
            ],
            color=ui.color,
        )
    )
    return 1 if result["validation_errors"] else 0


def cmd_bootstrap(args: argparse.Namespace) -> int:
    root = repo_root(args.root)
    ui = TerminalUI(mode=args.ui_mode)

    from hx.bootstrap import run_bootstrap
    from hx.setup import detect_primary_language

    with ui.activity(
        "Scaffolding agent config files",
        success_message="Agent config scaffolded",
    ) as activity:
        activity.update("Generating .claude/ directory")
        language = detect_primary_language(root)
        result = run_bootstrap(root, force=args.force, language=language)

    if result.get("error"):
        ui.note(result["error"], level="error")
        return 1

    if result["files_written"]:
        print("Files written:")
        for f in result["files_written"]:
            print(f"  {f}")
    else:
        print("All files already exist (use --force to overwrite)")

    print(
        render_action_card(
            "Agent Ready",
            [
                "Claude Code will auto-discover .claude/CLAUDE.md",
                "Codex will use AGENTS.md and TOOLS.md",
                "Run `hx run '<task>'` to start a governed task",
            ],
            color=ui.color,
        )
    )
    return 0


def cmd_percolation(args: argparse.Namespace) -> int:
    root = repo_root(args.root)
    ui = TerminalUI(mode=args.ui_mode)

    from hx.reasoning import percolation_status

    with ui.activity(
        "Checking percolation status",
        success_message="Percolation check complete",
    ):
        status = percolation_status(root)

    if args.json:
        print(json.dumps(status, indent=2))
    else:
        if not status.get("available"):
            print("No hexmap available.")
            return 1
        phase = status["global_phase"]
        occ = status["global_occupation"]
        threshold = status["threshold"]
        print(f"Global occupation: {occ:.4f} / {threshold}")
        print(f"Phase: {phase}")
        print(f"Recommendation: {status['recommendation']}")
        if status.get("parent_groups"):
            print()
            for pg in status["parent_groups"]:
                print(
                    f"  {pg['parent_id']}: occ={pg['occupation']:.4f} "
                    f"bdry={pg['boundary_occupation']:.4f} "
                    f"[{pg['phase']}]"
                )
    return 0


def cmd_reasoning_gate(args: argparse.Namespace) -> int:
    root = repo_root(args.root)
    ui = TerminalUI(mode=args.ui_mode)

    from hx.reasoning import reasoning_gate

    hexmap = load_hexmap(root)
    cell_id = args.cell or hexmap.cells[0].cell_id

    with ui.activity(
        "Evaluating reasoning gate",
        success_message="Reasoning gate evaluated",
    ):
        result = reasoning_gate(root, cell_id, args.radius)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Mode: {result['mode']}")
        print(f"Justification: {result['justification']}")
        signals = result["signals"]
        print("Signals:")
        print(f"  occupation: {signals.get('occupation_fraction', '?')}")
        print(f"  pressure:   {signals.get('boundary_pressure', '?')}")
        print(f"  max risk:   {signals.get('max_port_risk', '?')}")
        print(f"  hot edges:  {signals.get('hot_edge_count', 0)}")
        if result["hot_edges"]:
            print("Hot edges:")
            for e in result["hot_edges"][:5]:
                print(
                    f"  {e['from']}->{e['to']} "
                    f"risk={e['risk']:.3f} weight={e['weight']:.2f}"
                )
    return 0


def cmd_samples(args: argparse.Namespace) -> int:
    ui = TerminalUI(mode=args.ui_mode)
    from hx.planner import render_samples
    print(render_samples(color=ui.color))
    return 0


def cmd_plan_create(args: argparse.Namespace) -> int:
    root = repo_root(args.root)
    ui = TerminalUI(mode=args.ui_mode)
    from hx.planner import create_plan, render_plan

    steps: list[dict] = []
    for i, desc in enumerate(args.step or []):
        cell = None
        radius = 1
        depends_on: list[int] = []
        # Parse --step-cell and --step-after if provided
        if args.step_cell and i < len(args.step_cell):
            cell = args.step_cell[i]
        if args.step_after and i < len(args.step_after):
            depends_on = [int(x) for x in args.step_after[i].split(",") if x]
        steps.append({
            "description": desc,
            "cell": cell,
            "radius": radius,
            "depends_on": depends_on,
        })

    if not steps:
        ui.note(
            "No steps provided. Use --step 'description' (repeatable).\n"
            "  Example: hx plan create 'Migrate to v2' "
            "--step 'Update models' --step 'Add tests'",
            level="error",
        )
        return 1

    try:
        plan = create_plan(root, args.goal, steps)
    except ValueError as exc:
        ui.note(str(exc), level="error")
        return 1

    print(render_plan(plan, color=ui.color))
    return 0


def cmd_plan_show(args: argparse.Namespace) -> int:
    root = repo_root(args.root)
    ui = TerminalUI(mode=args.ui_mode)
    from hx.planner import load_plan, render_plan

    plan = load_plan(root)
    if plan is None:
        ui.note("No active plan. Create one with `hx plan create`.", level="error")
        return 1

    if args.json:
        print(json.dumps(plan, indent=2))
    else:
        print(render_plan(plan, color=ui.color))
    return 0


def cmd_plan_advance(args: argparse.Namespace) -> int:
    root = repo_root(args.root)
    ui = TerminalUI(mode=args.ui_mode)
    from hx.planner import advance_plan, render_plan

    try:
        plan = advance_plan(root, args.step, status=args.status)
    except (RuntimeError, ValueError) as exc:
        ui.note(str(exc), level="error")
        return 1

    print(render_plan(plan, color=ui.color))
    return 0


def cmd_readiness(args: argparse.Namespace) -> int:
    root = repo_root(args.root)
    ui = TerminalUI(mode=args.ui_mode)

    from hx.readiness import check_readiness, render_readiness

    with ui.activity(
        "Checking project readiness",
        success_message="Readiness check complete",
    ):
        report = check_readiness(root)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(render_readiness(report, color=ui.color))
    return 0 if report["ready"] else 1


def cmd_suggest(args: argparse.Namespace) -> int:
    root = repo_root(args.root)
    ui = TerminalUI(mode=args.ui_mode)

    from hx.suggest import suggest_tasks

    with ui.activity(
        "Analyzing repo for task suggestions",
        success_message="Task suggestions ready",
    ):
        suggestions = suggest_tasks(root)

    if not suggestions:
        print("No suggestions — your project looks good!")
        return 0

    limit = args.n
    if args.json:
        print(json.dumps(suggestions[:limit], indent=2))
    else:
        for i, s in enumerate(suggestions[:limit], 1):
            risk_label = s["risk"]
            if ui.color:
                from hx.ui import paint
                risk_colors = {
                    "none": "green", "low": "green",
                    "medium": "yellow", "high": "red",
                }
                risk_label = paint(
                    risk_label, risk_colors.get(s["risk"], "dim"),
                    color=True,
                )
            cell_str = f" (cell: {s['cell']})" if s["cell"] else ""
            print(f"{i}. [{risk_label}] {s['task']}{cell_str}")
            print(f"   {s['reason']}")
            print(f"   $ {s['command']}")
            print()

    return 0


def cmd_run(args: argparse.Namespace) -> int:
    root = repo_root(args.root)
    ui = TerminalUI(mode=args.ui_mode)

    provider = args.provider
    from hx.providers import resolve_api_key, resolve_provider
    try:
        config = resolve_provider(provider)
    except ValueError as exc:
        ui.note(str(exc), level="error")
        return 1

    api_key = resolve_api_key(provider)
    if not api_key:
        env_key = config["env_key"]
        name = config["name"]
        ui.note(
            f"{env_key} not set. To use hx run with {name}:\n"
            f"  1. Get an API key from your provider\n"
            f"  2. export {env_key}='your-key-here'\n"
            f"  3. Re-run your command",
            level="error",
        )
        return 1

    # Resolve cell from CWD or --cell
    if args.cell:
        active_cell_id = args.cell
    else:
        hexmap = load_hexmap(root)
        try:
            cwd_rel = str(Path.cwd().relative_to(root))
        except ValueError:
            cwd_rel = ""
        from hx.hexmap import resolve_cell_id as resolve_cid

        active_cell_id = resolve_cid(hexmap, cwd_rel) if cwd_rel else None
        if active_cell_id is None and hexmap.cells:
            active_cell_id = hexmap.cells[0].cell_id
        if active_cell_id is None:
            cell_ids = [c.cell_id for c in hexmap.cells] if hexmap.cells else []
            ui.note(
                "Could not resolve active cell from current directory.\n"
                f"  Available cells: {', '.join(cell_ids) or 'none'}\n"
                "  Use --cell <cell_id> to specify explicitly.\n"
                "  Run `hx hex show <cell_id>` to inspect a cell.",
                level="error",
            )
            return 1

    from hx.agent import run_agent

    result = run_agent(
        root,
        args.task,
        active_cell_id=active_cell_id,
        radius=args.radius,
        model=args.model,
        provider=provider,
        max_turns=args.max_turns,
        color=ui.color,
        api_key=api_key,
    )
    return 0 if result.get("status") == "ok" else 1


def cmd_status(args: argparse.Namespace) -> int:
    root = repo_root(args.root)
    ui = TerminalUI(mode=args.ui_mode)

    from hx.status import gather_status, render_status

    if args.json:
        data = gather_status(root)
        # Serialize AuditRun objects
        data["recent_runs"] = [
            {"run_id": r.run_id, "command": r.command, "status": r.status}
            for r in data["recent_runs"]
        ]
        data["open_runs"] = [
            {"run_id": r.run_id, "command": r.command}
            for r in data["open_runs"]
        ]
        print(json.dumps(data, indent=2))
    else:
        print(render_status(root, color=ui.color))
    return 0


def cmd_mcp_serve(args: argparse.Namespace) -> int:
    from hx.mcp_server import create_server_with_options

    ui = TerminalUI(mode=args.ui_mode)
    ui.note(
        f"Starting MCP server over {args.transport} from {repo_root(args.root)}",
        level="info",
    )
    if args.transport == "stdio":
        ui.note("Ready for Codex or Gemini MCP stdio clients", level="success")
    server = create_server_with_options(
        repo_root(args.root),
        host=args.host,
        port=args.port,
    )
    server.run(transport=args.transport)
    return 0


def cmd_benchmark_run(args: argparse.Namespace) -> int:
    root = repo_root(args.root)
    ui = TerminalUI(mode=args.ui_mode)
    battery_path = Path(args.battery).resolve()

    with ui.activity(
        "Running benchmark battery",
        success_message="Benchmark run complete",
    ) as activity:

        def progress(event: str, payload: dict[str, object]) -> None:
            if event == "load_battery":
                activity.update(f"Loading benchmark battery {battery_path.name}")
            elif event == "battery_valid":
                activity.note(
                    f"Validated {payload['task_count']} benchmark task(s)",
                    level="info",
                )
            elif event == "task_start":
                activity.update(
                    f"Running task {payload['task_id']} ({payload['repeats']} repeat(s))"
                )
                activity.note(
                    f"task={payload['task_id']} repeats={payload['repeats']}",
                    level="detail",
                )
            elif event == "condition_done":
                outcome = "passed" if payload["success"] else "failed"
                activity.note(
                    f"{payload['task_id']} {payload['condition']} "
                    f"{payload['repeat']}/{payload['repeats']} {outcome}",
                    level="detail" if payload["success"] else "warning",
                )
                activity.update(
                    f"Running task {payload['task_id']} ({payload['repeats']} repeat(s))"
                )
            elif event == "report_ready":
                activity.update(f"Writing benchmark report for {payload['task_count']} task(s)")

        report = run_benchmark(root, battery_path, progress=progress)
    print(json.dumps(report, indent=2))
    return 0


def cmd_benchmark_report(args: argparse.Namespace) -> int:
    root = repo_root(args.root)
    ui = TerminalUI(mode=args.ui_mode)
    with ui.activity(
        "Rendering benchmark markdown report",
        success_message="Rendered benchmark markdown report",
    ):
        report = report_benchmark(root)
    print(report)
    return 0


def cmd_benchmark_validate(args: argparse.Namespace) -> int:
    ui = TerminalUI(mode=args.ui_mode)
    battery_path = Path(args.battery).resolve()
    with ui.activity(
        "Validating benchmark battery",
        success_message="Validated benchmark battery",
    ) as activity:
        activity.update(f"Loading {battery_path.name}")
        tasks = load_task_battery(battery_path)
        activity.update("Checking task battery structure")
        errors = validate_task_battery(tasks)
        if errors:
            activity.fail("Benchmark battery validation failed")
            for error in errors:
                print(error)
            return 1
    print("Benchmark battery is valid")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = HxArgumentParser(prog="hx")
    parser.add_argument("--root", default=".")
    parser.add_argument(
        "--ui-mode",
        choices=["auto", "quiet", "normal", "expanded"],
        default="auto",
        help="terminal UX verbosity: quiet, normal, or expanded",
    )
    parser.add_argument(
        "--no-banner",
        action="store_true",
        help="suppress the macOS terminal startup screen in interactive help output",
    )
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Run a governed agent task")
    run_parser.add_argument("task", help="Task description in natural language")
    run_parser.add_argument(
        "--cell", default=None,
        help="Override active cell (auto-resolved from CWD)",
    )
    run_parser.add_argument("--radius", type=int, default=1)
    run_parser.add_argument(
        "--provider", default="anthropic",
        choices=["anthropic", "openai", "deepseek", "gemini"],
        help="LLM provider (default: anthropic)",
    )
    run_parser.add_argument(
        "--model", default=None,
        help="Model override (default: provider's default model)",
    )
    run_parser.add_argument("--max-turns", type=int, default=50)
    run_parser.set_defaults(func=cmd_run)

    status_parser = subparsers.add_parser("status", help="Show governance status dashboard")
    status_parser.add_argument("--json", action="store_true")
    status_parser.set_defaults(func=cmd_status)

    setup_parser = subparsers.add_parser(
        "setup", help="One-command guided onboarding",
    )
    setup_parser.add_argument("--force", action="store_true")
    setup_parser.set_defaults(func=cmd_setup)

    bootstrap_parser = subparsers.add_parser(
        "bootstrap", help="Scaffold agent-ready config files",
    )
    bootstrap_parser.add_argument("--force", action="store_true")
    bootstrap_parser.set_defaults(func=cmd_bootstrap)

    readiness_parser = subparsers.add_parser(
        "readiness", help="Check project readiness",
    )
    readiness_parser.add_argument("--json", action="store_true")
    readiness_parser.set_defaults(func=cmd_readiness)

    suggest_parser = subparsers.add_parser(
        "suggest", help="Suggest low-risk starter tasks",
    )
    suggest_parser.add_argument("-n", type=int, default=5)
    suggest_parser.add_argument("--json", action="store_true")
    suggest_parser.set_defaults(func=cmd_suggest)

    percolation_parser = subparsers.add_parser(
        "percolation", help="Real-time percolation status monitor",
    )
    percolation_parser.add_argument("--json", action="store_true")
    percolation_parser.set_defaults(func=cmd_percolation)

    gate_parser = subparsers.add_parser(
        "gate", help="Evaluate reasoning gate (local/scoped/full/escalate)",
    )
    gate_parser.add_argument(
        "--cell", default=None, help="Active cell ID",
    )
    gate_parser.add_argument("--radius", type=int, default=1)
    gate_parser.add_argument("--json", action="store_true")
    gate_parser.set_defaults(func=cmd_reasoning_gate)

    samples_parser = subparsers.add_parser(
        "samples", help="Show sample task prompts for hx run",
    )
    samples_parser.set_defaults(func=cmd_samples)

    plan_parser = subparsers.add_parser(
        "plan", help="Multi-step task planning",
    )
    plan_sub = plan_parser.add_subparsers(dest="plan_command", required=True)

    plan_create = plan_sub.add_parser("create", help="Create a task plan")
    plan_create.add_argument("goal", help="Overall goal description")
    plan_create.add_argument(
        "--step", action="append", help="Step description (repeatable)",
    )
    plan_create.add_argument(
        "--step-cell", action="append",
        help="Cell for corresponding step (repeatable)",
    )
    plan_create.add_argument(
        "--step-after", action="append",
        help="Dependencies as comma-separated step indices (repeatable)",
    )
    plan_create.set_defaults(func=cmd_plan_create)

    plan_show = plan_sub.add_parser("show", help="Show current plan")
    plan_show.add_argument("--json", action="store_true")
    plan_show.set_defaults(func=cmd_plan_show)

    plan_advance = plan_sub.add_parser("advance", help="Mark step as done")
    plan_advance.add_argument("step", type=int, help="Step index")
    plan_advance.add_argument(
        "--status", default="completed",
        help="Status to set (default: completed)",
    )
    plan_advance.set_defaults(func=cmd_plan_advance)

    init_parser = subparsers.add_parser("init")
    init_parser.add_argument("--force", action="store_true")
    init_parser.set_defaults(func=cmd_init)

    start_parser = subparsers.add_parser(
        "start",
        help="Describe your project and the assistant scaffolds everything",
    )
    start_parser.add_argument(
        "prompt",
        help="Describe what you want to build (e.g., 'a recipe management web app')",
    )
    start_parser.add_argument(
        "--language", default=None,
        help="Override auto-detected language (e.g., python, typescript)",
    )
    start_parser.add_argument("--force", action="store_true")
    start_parser.set_defaults(func=cmd_start)

    provider_parser = subparsers.add_parser(
        "provider", help="Unified LLM provider setup and status",
    )
    provider_sub = provider_parser.add_subparsers(
        dest="provider_command", required=True,
    )
    provider_setup = provider_sub.add_parser(
        "setup", help="Interactive provider setup wizard",
    )
    provider_setup.add_argument(
        "--provider", dest="provider_name", default=None,
        choices=["anthropic", "openai", "deepseek", "gemini"],
        help="Pre-select provider (skip menu)",
    )
    provider_setup.add_argument(
        "--non-interactive", action="store_true",
        help="Run without prompts (requires --provider and env key)",
    )
    provider_setup.add_argument(
        "--skip-validation", action="store_true",
        help="Skip API key validation",
    )
    provider_setup.set_defaults(func=cmd_provider_setup)
    provider_status_cmd = provider_sub.add_parser(
        "status", help="Show configured provider status",
    )
    provider_status_cmd.add_argument("--json", action="store_true")
    provider_status_cmd.set_defaults(func=cmd_provider_status)

    codex_parser = subparsers.add_parser("codex")
    codex_sub = codex_parser.add_subparsers(dest="codex_command", required=True)
    codex_setup = codex_sub.add_parser("setup")
    codex_setup.set_defaults(func=cmd_codex_setup)
    codex_status_cmd = codex_sub.add_parser("status")
    codex_status_cmd.set_defaults(func=cmd_codex_status)

    gemini_parser = subparsers.add_parser("gemini")
    gemini_sub = gemini_parser.add_subparsers(
        dest="gemini_command", required=True,
    )
    gemini_setup = gemini_sub.add_parser("setup")
    gemini_setup.set_defaults(func=cmd_gemini_setup)
    gemini_status_cmd = gemini_sub.add_parser("status")
    gemini_status_cmd.set_defaults(func=cmd_gemini_status)

    memory_parser = subparsers.add_parser("memory")
    memory_sub = memory_parser.add_subparsers(dest="memory_command", required=True)
    memory_summarize = memory_sub.add_parser("summarize")
    memory_summarize.add_argument("--json", action="store_true")
    memory_summarize.set_defaults(func=cmd_memory_summarize)
    memory_status_cmd = memory_sub.add_parser("status")
    memory_status_cmd.set_defaults(func=cmd_memory_status)

    resume_parser = subparsers.add_parser("resume")
    resume_parser.set_defaults(func=cmd_resume)

    hex_parser = subparsers.add_parser("hex")
    hex_sub = hex_parser.add_subparsers(dest="hex_command", required=True)
    hex_build = hex_sub.add_parser("build")
    hex_build.set_defaults(func=cmd_hex_build)
    hex_validate = hex_sub.add_parser("validate")
    hex_validate.set_defaults(func=cmd_hex_validate)
    hex_show = hex_sub.add_parser("show")
    hex_show.add_argument("cell_id")
    hex_show.add_argument("--radius", type=int, default=1)
    hex_show.add_argument("--include-parent", action="store_true")
    hex_show.add_argument("--json", action="store_true")
    hex_show.set_defaults(func=cmd_hex_show)
    hex_watch = hex_sub.add_parser("watch")
    hex_watch.add_argument("cell_id")
    hex_watch.add_argument("--radius", type=int, default=1)
    hex_watch.add_argument("--interval", type=float, default=1.0)
    hex_watch.add_argument("--iterations", type=int, default=0)
    hex_watch.set_defaults(func=cmd_hex_watch)
    hex_parent = hex_sub.add_parser("parent")
    hex_parent_sub = hex_parent.add_subparsers(dest="parent_command", required=True)
    hex_parent_show = hex_parent_sub.add_parser("show")
    hex_parent_show.add_argument("parent_id")
    hex_parent_show.add_argument("--json", action="store_true")
    hex_parent_show.set_defaults(func=cmd_hex_parent_show)
    hex_parent_watch = hex_parent_sub.add_parser("watch")
    hex_parent_watch.add_argument("parent_id")
    hex_parent_watch.add_argument("--interval", type=float, default=1.0)
    hex_parent_watch.add_argument("--iterations", type=int, default=0)
    hex_parent_watch.set_defaults(func=cmd_hex_parent_watch)
    hex_parent_summarize = hex_parent_sub.add_parser("summarize")
    hex_parent_summarize.add_argument("parent_id")
    hex_parent_summarize.set_defaults(func=cmd_hex_parent_summarize)

    mcp_parser = subparsers.add_parser("mcp")
    mcp_sub = mcp_parser.add_subparsers(dest="mcp_command", required=True)
    mcp_serve = mcp_sub.add_parser("serve")
    mcp_serve.add_argument("--transport", default="stdio")
    mcp_serve.add_argument("--host", default="127.0.0.1")
    mcp_serve.add_argument("--port", type=int, default=8000)
    mcp_serve.set_defaults(func=cmd_mcp_serve)

    doctor_parser = subparsers.add_parser("doctor")
    doctor_parser.set_defaults(func=cmd_doctor)

    log_parser = subparsers.add_parser("log")
    log_parser.add_argument("-n", type=int, default=10)
    log_parser.set_defaults(func=cmd_log)

    replay_parser = subparsers.add_parser("replay")
    replay_parser.add_argument("audit_run_id")
    replay_parser.set_defaults(func=cmd_replay)

    benchmark_parser = subparsers.add_parser("benchmark")
    benchmark_sub = benchmark_parser.add_subparsers(dest="benchmark_command", required=True)
    benchmark_run = benchmark_sub.add_parser("run")
    benchmark_run.add_argument("battery")
    benchmark_run.set_defaults(func=cmd_benchmark_run)
    benchmark_validate = benchmark_sub.add_parser("validate")
    benchmark_validate.add_argument("battery")
    benchmark_validate.set_defaults(func=cmd_benchmark_validate)
    benchmark_report_cmd = benchmark_sub.add_parser("report")
    benchmark_report_cmd.set_defaults(func=cmd_benchmark_report)

    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--no-banner" in argv:
        os.environ["HX_NO_BANNER"] = "1"
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "no_banner", False):
        os.environ["HX_NO_BANNER"] = "1"
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
