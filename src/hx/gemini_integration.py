"""Gemini CLI integration: auto-configure MCP server for Gemini."""
from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

MANAGED_BEGIN = "// BEGIN HX GEMINI MCP"
MANAGED_END = "// END HX GEMINI MCP"


@dataclass
class GeminiStatus:
    config_path: Path
    hx_command: str
    gemini_installed: bool
    config_exists: bool
    hx_configured: bool


def gemini_home() -> Path:
    return Path(
        os.environ.get("GEMINI_HOME", Path.home() / ".gemini")
    ).expanduser()


def gemini_config_path() -> Path:
    return gemini_home() / "settings.json"


def resolve_hx_command() -> str:
    discovered = shutil.which("hx")
    if discovered:
        return discovered
    candidate = Path(sys.executable).resolve().with_name("hx")
    if candidate.exists():
        return str(candidate)
    return "hx"


def gemini_status() -> GeminiStatus:
    config_path = gemini_config_path()
    hx_configured = False
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text())
            servers = data.get("mcpServers", {})
            hx_configured = "hx" in servers
        except (json.JSONDecodeError, KeyError):
            pass
    return GeminiStatus(
        config_path=config_path,
        hx_command=resolve_hx_command(),
        gemini_installed=shutil.which("gemini") is not None,
        config_exists=config_path.exists(),
        hx_configured=hx_configured,
    )


def install_gemini_config(root: Path) -> GeminiStatus:
    """Write MCP server entry for hx into Gemini settings."""
    status = gemini_status()
    config_path = status.config_path
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Load existing config or start fresh
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text())
        except json.JSONDecodeError:
            data = {}
    else:
        data = {}

    # Ensure mcpServers key exists
    if "mcpServers" not in data:
        data["mcpServers"] = {}

    # Set hx MCP entry
    data["mcpServers"]["hx"] = {
        "command": status.hx_command,
        "args": [
            "--root", str(root.resolve()),
            "mcp", "serve", "--transport", "stdio",
        ],
    }

    config_path.write_text(json.dumps(data, indent=2) + "\n")
    return gemini_status()
