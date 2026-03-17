from __future__ import annotations

import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

MANAGED_BEGIN = "# BEGIN HX CODEX MCP"
MANAGED_END = "# END HX CODEX MCP"
HX_SECTION_RE = re.compile(
    r"(?ms)^\[mcp_servers\.hx\]\n(?:^(?!\[).*(?:\n|$))*"
)
MANAGED_BLOCK_RE = re.compile(
    rf"(?ms)^\s*{re.escape(MANAGED_BEGIN)}\n.*?{re.escape(MANAGED_END)}\n?"
)


@dataclass
class CodexStatus:
    config_path: Path
    hx_command: str
    codex_installed: bool
    config_exists: bool
    hx_configured: bool


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()


def codex_config_path() -> Path:
    return codex_home() / "config.toml"


def resolve_hx_command() -> str:
    discovered = shutil.which("hx")
    if discovered:
        return discovered
    candidate = Path(sys.executable).resolve().with_name("hx")
    if candidate.exists():
        return str(candidate)
    return "hx"


def codex_status() -> CodexStatus:
    config_path = codex_config_path()
    text = config_path.read_text() if config_path.exists() else ""
    return CodexStatus(
        config_path=config_path,
        hx_command=resolve_hx_command(),
        codex_installed=shutil.which("codex") is not None,
        config_exists=config_path.exists(),
        hx_configured="[mcp_servers.hx]" in text,
    )


def render_hx_mcp_block(root: Path, hx_command: str) -> str:
    args = json.dumps(
        ["--root", str(root.resolve()), "mcp", "serve", "--transport", "stdio"]
    )
    return "\n".join(
        [
            MANAGED_BEGIN,
            "[mcp_servers.hx]",
            f"command = {json.dumps(hx_command)}",
            f"args = {args}",
            MANAGED_END,
            "",
        ]
    )


def _strip_existing_hx_block(text: str) -> str:
    stripped = MANAGED_BLOCK_RE.sub("", text)
    stripped = HX_SECTION_RE.sub("", stripped)
    return stripped.strip()


def install_codex_config(root: Path) -> CodexStatus:
    status = codex_status()
    config_path = status.config_path
    config_path.parent.mkdir(parents=True, exist_ok=True)
    existing = config_path.read_text() if config_path.exists() else ""
    cleaned = _strip_existing_hx_block(existing)
    managed = render_hx_mcp_block(root, status.hx_command).rstrip()
    updated = f"{cleaned}\n\n{managed}\n" if cleaned else f"{managed}\n"
    config_path.write_text(updated)
    return codex_status()
