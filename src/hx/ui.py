from __future__ import annotations

import os
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from shutil import get_terminal_size
from textwrap import shorten
from typing import Any, TextIO

from hx.authz import allowed_cells
from hx.models import AuditRun, HexMap, Port
from hx.parents import parent_group_map, parent_summary

RESET = "\033[0m"
COLORS = {
    "cyan": "\033[38;5;45m",
    "blue": "\033[38;5;39m",
    "green": "\033[38;5;42m",
    "yellow": "\033[38;5;220m",
    "red": "\033[38;5;203m",
    "dim": "\033[2m",
    "bold": "\033[1m",
}
SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
SIDE_LABELS = ["N", "NE", "SE", "S", "SW", "NW"]


def is_tty(stream: TextIO | None) -> bool:
    if stream is None:
        return False
    isatty = getattr(stream, "isatty", None)
    return bool(isatty and isatty())


def should_use_color(stream: TextIO | None) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("HX_NO_COLOR", "").lower() in {"1", "true", "yes"}:
        return False
    term = os.environ.get("TERM", "")
    return is_tty(stream) and term != "dumb"


def should_use_spinner(stream: TextIO | None) -> bool:
    if os.environ.get("CI"):
        return False
    if os.environ.get("HX_NO_SPINNER", "").lower() in {"1", "true", "yes"}:
        return False
    return is_tty(stream)


def resolve_ui_mode(mode: str, stream: TextIO | None) -> str:
    if mode == "auto":
        return "normal" if is_tty(stream) else "quiet"
    return mode


def paint(text: str, *styles: str, color: bool = False) -> str:
    if not color or not styles:
        return text
    prefix = "".join(COLORS[style] for style in styles if style in COLORS)
    if not prefix:
        return text
    return f"{prefix}{text}{RESET}"


def format_status_line(
    message: str,
    *,
    kind: str,
    frame: str | None = None,
    color: bool = False,
) -> str:
    if kind == "working":
        glyph = paint(frame or "…", "cyan", color=color)
        label = paint("thinking", "dim", color=color)
        return f"{glyph} {message} {label}"
    if kind == "success":
        return f"{paint('✓', 'bold', 'green', color=color)} {message}"
    if kind == "error":
        return f"{paint('✗', 'bold', 'red', color=color)} {message}"
    if kind == "warning":
        return f"{paint('!', 'bold', 'yellow', color=color)} {message}"
    return message


def render_startup_screen(version: str, *, color: bool = False) -> str:
    title = paint(f"hx {version}", "bold", "cyan", color=color)
    subtitle = paint("hex-governed local coding harness", "blue", color=color)
    target = paint("supported target: macOS terminal sessions", "yellow", color=color)
    quick = paint("Quick start", "bold", "green", color=color)
    prereqs = paint("Prerequisites", "bold", "green", color=color)
    return "\n".join(
        [
            "┌──────────────────────────────────────────────────────────────┐",
            f"│ {title:<61}│",
            f"│ {subtitle:<61}│",
            f"│ {target:<61}│",
            "└──────────────────────────────────────────────────────────────┘",
            "",
            quick,
            f"  {paint('hx init', 'cyan', color=color)}",
            f"  {paint('hx hex build', 'cyan', color=color)}",
            f"  {paint('hx hex validate', 'cyan', color=color)}",
            f"  {paint('hx codex setup', 'cyan', color=color)}",
            f"  {paint('hx mcp serve --transport stdio', 'cyan', color=color)}",
            "",
            prereqs,
            "  macOS terminal session",
            "  python3 (3.11+)",
            "  git (Xcode Command Line Tools is fine)",
            "",
        ]
    )


@dataclass
class Activity:
    ui: TerminalUI
    message: str
    success_message: str | None = None
    _running: bool = field(default=False, init=False)
    _message: str = field(init=False)
    _thread: threading.Thread | None = field(default=None, init=False)
    _frame_index: int = field(default=0, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    def __post_init__(self) -> None:
        self._message = self.message

    def __enter__(self) -> Activity:
        self._running = True
        if self.ui.spinner:
            self._thread = threading.Thread(target=self._spin, daemon=True)
            self._thread.start()
        else:
            self.ui.write_line(
                format_status_line(self._message, kind="working", color=self.ui.color)
            )
        return self

    def update(self, message: str) -> None:
        with self._lock:
            self._message = message

    def note(self, message: str, *, level: str = "info") -> None:
        self.ui.note(message, level=level)

    def succeed(self, message: str | None = None) -> None:
        if self._running:
            self._finish(message or self.success_message or self._message, kind="success")

    def fail(self, message: str | None = None) -> None:
        if self._running:
            self._finish(message or self._message, kind="error")

    def __exit__(self, exc_type, _exc, _tb) -> bool:
        if exc_type is not None:
            self.fail(f"{self._message} failed")
            return False
        self.succeed()
        return False

    def _spin(self) -> None:
        while self._running:
            with self._lock:
                frame = SPINNER_FRAMES[self._frame_index % len(SPINNER_FRAMES)]
                message = self._message
                self._frame_index += 1
            self.ui.write_inline(
                format_status_line(message, kind="working", frame=frame, color=self.ui.color)
            )
            time.sleep(0.08)

    def _finish(self, message: str, *, kind: str) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=0.2)
        if self.ui.spinner:
            self.ui.clear_inline()
        self.ui.write_line(format_status_line(message, kind=kind, color=self.ui.color))


class TerminalUI:
    def __init__(self, stream: TextIO | None = None, *, mode: str = "auto") -> None:
        self.stream = stream or sys.stderr
        self.mode = resolve_ui_mode(mode, self.stream)
        self.color = should_use_color(self.stream)
        self.spinner = self.mode in {"normal", "expanded"} and should_use_spinner(self.stream)

    def activity(self, message: str, *, success_message: str | None = None) -> Activity:
        return Activity(self, message, success_message=success_message)

    def note(self, message: str, *, level: str = "info") -> None:
        if self.mode == "quiet":
            return
        if level == "detail" and self.mode != "expanded":
            return
        labels = {
            "info": ("info", "blue"),
            "success": ("ok", "green"),
            "warning": ("warn", "yellow"),
            "error": ("error", "red"),
            "detail": ("task", "cyan"),
        }
        label, color_name = labels.get(level, ("info", "blue"))
        prefix = paint(f"[{label}]", "bold", color_name, color=self.color)
        self.write_line(f"{prefix} {message}")

    def write_inline(self, text: str) -> None:
        self.stream.write("\r\033[2K" + text)
        self.stream.flush()

    def clear_inline(self) -> None:
        self.stream.write("\r\033[2K")
        self.stream.flush()

    def write_line(self, text: str) -> None:
        self.stream.write(text + "\n")
        self.stream.flush()


def port_fulfillment_status(hexmap: HexMap, cell_id: str, side_index: int) -> str:
    cell = hexmap.cell(cell_id)
    neighbor = cell.neighbors[side_index]
    port = cell.ports[side_index]
    if neighbor is None and port is None:
        return "empty"
    if neighbor is None and port is not None:
        return "stray-port"
    if neighbor is not None and port is None:
        return "neighbor-only"
    assert isinstance(port, Port)
    if port.neighbor_cell_id not in {None, neighbor}:
        return "mismatch"
    neighbor_cell = hexmap.cell(neighbor)
    if cell_id not in neighbor_cell.neighbors:
        return "asymmetric"
    return "fulfilled"


def render_hex_view(
    hexmap: HexMap,
    active_cell_id: str,
    radius: int,
    *,
    color: bool = False,
) -> str:
    cell = hexmap.cell(active_cell_id)
    scope = allowed_cells(hexmap, active_cell_id, radius)
    statuses = [port_fulfillment_status(hexmap, active_cell_id, index) for index in range(6)]
    fulfilled = sum(1 for status in statuses if status == "fulfilled")

    def side_line(index: int) -> str:
        neighbor = cell.neighbors[index] or "null"
        in_scope = neighbor in scope if neighbor != "null" else False
        scope_mark = "*" if in_scope else "-"
        status = statuses[index]
        label = paint(f"[{SIDE_LABELS[index]:>2}]", "cyan", color=color)
        center = paint(active_cell_id, "bold", "green", color=color)
        return f"{label} {neighbor:<18} {status:<12} scope:{scope_mark} center:{center}"

    title = paint(f"Hex view for {active_cell_id} (R{radius})", "bold", "blue", color=color)
    summary = paint(
        f"fulfilled sides: {fulfilled}/6 | allowed cells: {', '.join(scope)}",
        "yellow",
        color=color,
    )
    lines = [
        title,
        summary,
        "",
        f"                 {side_line(0)}",
        f"      {side_line(5)}",
        f"                        {paint(active_cell_id, 'bold', 'green', color=color)}",
        f"      {side_line(4)}",
        f"                 {side_line(3)}",
        "",
        f"                 {side_line(1)}",
        f"                 {side_line(2)}",
    ]
    return "\n".join(lines)


def terminal_width(default: int = 100) -> int:
    return get_terminal_size((default, 30)).columns


def clear_screen(stream: TextIO) -> None:
    stream.write("\033[H\033[2J")
    stream.flush()


def _panel(title: str, lines: list[str], width: int, *, color: bool) -> list[str]:
    inner = max(width - 4, 8)
    heading = paint(title[:inner], "bold", "blue", color=color)
    rendered = [f"┌{'─' * (width - 2)}┐", f"│ {heading:<{inner}} │"]
    for line in lines:
        rendered.append(f"│ {line[:inner]:<{inner}} │")
    rendered.append(f"└{'─' * (width - 2)}┘")
    return rendered


def _combine_columns(left: list[str], right: list[str], gap: str = "  ") -> str:
    height = max(len(left), len(right))
    left_width = max((len(line) for line in left), default=0)
    lines = []
    for index in range(height):
        left_line = left[index] if index < len(left) else " " * left_width
        right_line = right[index] if index < len(right) else ""
        lines.append(f"{left_line:<{left_width}}{gap}{right_line}")
    return "\n".join(lines)


def _status_color(status: str) -> str:
    if status == "ok":
        return "green"
    if status in {"failed", "error"}:
        return "red"
    return "yellow"


def _recent_runs_lines(runs: list[AuditRun], width: int, *, color: bool) -> list[str]:
    if not runs:
        return [paint("no audit runs yet", "dim", color=color)]
    lines = []
    inner = max(width - 8, 8)
    for run in runs[:6]:
        status = paint(run.status, _status_color(run.status), color=color)
        label = shorten(f"{run.command} {run.run_id[:8]}", width=inner, placeholder="...")
        lines.append(f"{label} [{status}]")
    return lines


def _recent_events_lines(runs: list[AuditRun], width: int, *, color: bool) -> list[str]:
    events: list[tuple[str, str]] = []
    inner = max(width - 8, 8)
    for run in runs:
        for event in run.events[-10:]:
            stamp = event.timestamp.split("T")[-1][:8]
            payload = ", ".join(f"{k}={v}" for k, v in list(event.payload.items())[:2])
            text = shorten(
                f"{stamp} {run.command} {event.event_type} {payload}",
                width=inner,
                placeholder="...",
            )
            events.append((event.timestamp, text))
    if not events:
        return [paint("no audit events yet", "dim", color=color)]
    events.sort(reverse=True)
    return [line for _, line in events[:8]]


def _filter_runs_for_cells(runs: list[AuditRun], cell_ids: set[str]) -> list[AuditRun]:
    filtered = []
    for run in runs:
        active_cell = run.active_cell_id in cell_ids if run.active_cell_id is not None else False
        overlap = bool(set(run.allowed_cells) & cell_ids)
        if active_cell or overlap:
            filtered.append(run)
    return filtered


def render_watch_dashboard(
    hexmap: HexMap,
    active_cell_id: str,
    radius: int,
    runs: list[AuditRun],
    *,
    tick: int,
    interval_s: float,
    parent_details: dict[str, Any] | None = None,
    color: bool = False,
    width: int | None = None,
) -> str:
    width = width or terminal_width()
    left_width = min(max(width // 2, 44), width - 28)
    right_width = max(width - left_width - 2, 26)
    hex_lines = render_hex_view(hexmap, active_cell_id, radius, color=color).splitlines()
    left_panel = _panel("Hex Neighborhood", hex_lines, left_width, color=color)
    right_sections: list[list[str]] = []
    if parent_details is not None:
        parent_lines = [
            f"parent_id={parent_details['parent_id']}",
            f"center={parent_details['center_cell_id']}",
            f"members={', '.join(parent_details['member_cells'])}",
            (
                "neighbors="
                + ", ".join(neighbor or "null" for neighbor in parent_details["derived_neighbors"])
            ),
            (
                "pressure="
                f"{parent_details['metrics']['parent_boundary_pressure']} "
                "potential="
                f"{parent_details['metrics']['parent_architecture_potential']}"
            ),
        ]
        right_sections.append(
            _panel("Parent Context", parent_lines, right_width, color=color)
        )
    right_runs = _panel(
        "Recent Runs",
        _recent_runs_lines(runs, right_width, color=color),
        right_width,
        color=color,
    )
    right_sections.append(right_runs)
    right_events = _panel(
        "Recent Events",
        _recent_events_lines(runs, right_width, color=color),
        right_width,
        color=color,
    )
    right_sections.append(right_events)
    timestamp = datetime.now().strftime("%H:%M:%S")
    header_text = (
        f"hx hex watch  cell={active_cell_id}  radius=R{radius}  "
        f"tick={tick}  interval={interval_s:.1f}s  {timestamp}"
    )
    header = paint(
        header_text,
        "bold",
        "cyan",
        color=color,
    )
    footer = paint("Ctrl-C to exit live watch", "dim", color=color)
    right_column: list[str] = []
    for index, section in enumerate(right_sections):
        if index:
            right_column.append("")
        right_column.extend(section)
    return "\n".join([header, "", _combine_columns(left_panel, right_column), "", footer])


def render_parent_view(
    hexmap: HexMap,
    parent_id: str,
    *,
    color: bool = False,
) -> str:
    group = parent_group_map(hexmap)[parent_id]
    title = paint(f"Parent view for {parent_id}", "bold", "blue", color=color)
    summary = paint(
        f"center={group.center_cell_id} | members={', '.join(group.member_cells())}",
        "yellow",
        color=color,
    )

    def child_line(index: int) -> str:
        child = group.children[index] or "null"
        neighbor = group.derived_neighbors[index] or "null"
        label = paint(f"[{SIDE_LABELS[index]:>2}]", "cyan", color=color)
        return f"{label} slot:{child:<16} parent-neighbor:{neighbor}"

    lines = [
        title,
        summary,
        "",
        f"                 {child_line(0)}",
        f"      {child_line(5)}",
        f"                        {paint(group.center_cell_id, 'bold', 'green', color=color)}",
        f"      {child_line(4)}",
        f"                 {child_line(3)}",
        "",
        f"                 {child_line(1)}",
        f"                 {child_line(2)}",
    ]
    return "\n".join(lines)


def render_parent_watch_dashboard(
    hexmap: HexMap,
    root: Path,
    parent_id: str,
    runs: list[AuditRun],
    *,
    tick: int,
    interval_s: float,
    color: bool = False,
    width: int | None = None,
) -> str:
    width = width or terminal_width()
    left_width = min(max(width // 2, 44), width - 28)
    right_width = max(width - left_width - 2, 26)
    summary = parent_summary(root, hexmap, parent_id)
    left_panel = _panel(
        "Parent Neighborhood",
        render_parent_view(hexmap, parent_id, color=color).splitlines(),
        left_width,
        color=color,
    )
    relevant_runs = _filter_runs_for_cells(
        runs,
        set(summary["member_cells"]),
    )
    neighbor_panel = _panel(
        "Neighboring Parents",
        [neighbor or "null" for neighbor in summary["derived_neighbors"]],
        right_width,
        color=color,
    )
    risk_lines = [
        f"{item['port_id']} risk={item['policy_risk_score']}"
        for item in summary["risky_ports"][:5]
    ] or [paint("no risky boundary ports", "dim", color=color)]
    risk_panel = _panel("Risky Boundary Ports", risk_lines, right_width, color=color)
    event_panel = _panel(
        "Recent Boundary Events",
        _recent_events_lines(relevant_runs, right_width, color=color),
        right_width,
        color=color,
    )
    summary_panel = _panel(
        "Parent Summary",
        [
            summary["summary"],
            f"pressure={summary['metrics']['parent_boundary_pressure']}",
            f"potential={summary['metrics']['parent_architecture_potential']}",
            f"cohesion={summary['metrics']['parent_cohesion']}",
        ],
        right_width,
        color=color,
    )
    timestamp = datetime.now().strftime("%H:%M:%S")
    header = paint(
        (
            f"hx parent watch  parent={parent_id}  tick={tick}  "
            "interval="
            f"{interval_s:.1f}s  risk="
            f"{summary['metrics']['parent_architecture_potential']}  "
            f"{timestamp}"
        ),
        "bold",
        "cyan",
        color=color,
    )
    footer = paint("Ctrl-C to exit parent watch", "dim", color=color)
    right_column = []
    for panel in [neighbor_panel, risk_panel, event_panel, summary_panel]:
        if right_column:
            right_column.append("")
        right_column.extend(panel)
    return "\n".join([header, "", _combine_columns(left_panel, right_column), "", footer])
