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
from hx.config import DEFAULT_HEXMAP, DEFAULT_POLICY, ensure_hx_dirs, repo_root
from hx.hexmap import build_hexmap, load_hexmap, save_hexmap, validate_hexmap
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
        errors = validate_hexmap(root, load_hexmap(root))
        if errors:
            activity.fail("HEXMAP validation failed")
            for error in errors:
                print(error)
            return 1
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

    init_parser = subparsers.add_parser("init")
    init_parser.add_argument("--force", action="store_true")
    init_parser.set_defaults(func=cmd_init)

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
