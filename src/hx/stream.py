"""Streaming terminal renderer for the agent loop."""
from __future__ import annotations

import sys

from hx.ui import paint


class StreamRenderer:
    """Renders streaming agent output to the terminal."""

    def __init__(self, *, color: bool = False) -> None:
        self.color = color
        self._in_text = False

    def session_start(self, cell_id: str, radius: int, task: str) -> None:
        header = paint("hx run", "bold", "blue", color=self.color)
        cell_label = paint(cell_id, "bold", "green", color=self.color)
        print(f"{header}  cell={cell_label}  R{radius}")
        print(paint(f"Task: {task}", "dim", color=self.color))
        print(paint("─" * 60, "dim", color=self.color))
        print()

    def text_delta(self, text: str) -> None:
        if not self._in_text:
            self._in_text = True
        sys.stdout.write(text)
        sys.stdout.flush()

    def text_done(self) -> None:
        if self._in_text:
            sys.stdout.write("\n")
            sys.stdout.flush()
            self._in_text = False

    def tool_start(self, name: str, arguments: dict) -> None:
        self.text_done()
        label = paint(f"  ▸ {name}", "cyan", color=self.color)
        args_summary = _compact_args(arguments)
        if args_summary:
            print(f"{label} {paint(args_summary, 'dim', color=self.color)}")
        else:
            print(label)

    def tool_result(self, name: str, result: dict, *, error: str | None = None) -> None:
        if error:
            msg = paint(f"  ✗ {name}: {error}", "red", color=self.color)
            print(msg)
        else:
            summary = _compact_result(name, result)
            msg = paint(f"  ✓ {name}", "green", color=self.color)
            if summary:
                msg += " " + paint(summary, "dim", color=self.color)
            print(msg)

    def approval_prompt(self, reasons: list[str]) -> bool:
        self.text_done()
        print()
        msg = "⚠  Breaking change detected — approval required:"
        print(paint(msg, "bold", "yellow", color=self.color))
        for reason in reasons:
            print(paint(f"   • {reason}", "yellow", color=self.color))
        print()
        try:
            answer = input(paint("  Approve? [y/N]: ", "bold", color=self.color))
        except (EOFError, KeyboardInterrupt):
            print()
            return False
        return answer.strip().lower() in {"y", "yes"}

    def error(self, message: str) -> None:
        self.text_done()
        print(paint(f"Error: {message}", "red", color=self.color))

    def session_end(self, status: str, tool_call_count: int) -> None:
        self.text_done()
        print()
        print(paint("─" * 60, "dim", color=self.color))
        color_name = "green" if status == "ok" else "red"
        label = paint(status, "bold", color_name, color=self.color)
        print(f"Status: {label}  |  Tool calls: {tool_call_count}")


def _compact_args(arguments: dict) -> str:
    """One-line summary of tool arguments."""
    parts = []
    for key, value in arguments.items():
        if isinstance(value, str) and len(value) > 60:
            parts.append(f"{key}=<{len(value)} chars>")
        elif isinstance(value, list):
            parts.append(f"{key}=[{len(value)} items]")
        elif isinstance(value, dict):
            parts.append(f"{key}={{...}}")
        else:
            parts.append(f"{key}={value}")
    return " ".join(parts)


def _compact_result(name: str, result: dict) -> str:
    """One-line summary of a tool result."""
    if "cell_id" in result:
        return f"→ {result['cell_id']}"
    if "cells" in result:
        cells = result["cells"]
        if isinstance(cells, list):
            return f"→ {len(cells)} cells"
    if "files" in result:
        return f"→ {len(result['files'])} files"
    if "matches" in result:
        return f"→ {len(result['matches'])} matches"
    if "requires_approval" in result:
        if result["requires_approval"]:
            return "→ approval required"
        return "→ no approval needed"
    if "status" in result:
        return f"→ {result['status']}"
    if "ok" in result:
        return "→ ok" if result["ok"] else "→ failed"
    if "diff" in result:
        return f"→ {len(result['diff'])} chars"
    if "markdown" in result:
        return f"→ {len(result['markdown'])} chars"
    return ""
