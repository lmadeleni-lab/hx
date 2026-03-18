"""Unified provider setup wizard for hx.

Login-first interactive wizard that walks users through:
1. Choosing an LLM provider (Claude, Codex/OpenAI, DeepSeek, Gemini)
2. Browser-based login / OAuth flow (primary) or API key fallback
3. Validating credentials work
4. Persisting provider config to .hx/provider.toml
5. Setting up MCP integration for the chosen agent CLI
6. Scaffolding the initial project structure
"""
from __future__ import annotations

import http.server
import json
import os
import shutil
import subprocess
import sys
import threading
import urllib.parse
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hx.providers import PROVIDERS, resolve_provider

PROVIDER_CONFIG_FILE = ".hx/provider.toml"

# Auth URLs — these open the provider's login/console page
AUTH_URLS: dict[str, dict[str, str]] = {
    "anthropic": {
        "login": "https://console.anthropic.com/login",
        "keys": "https://console.anthropic.com/settings/keys",
        "signup": "https://console.anthropic.com/signup",
    },
    "openai": {
        "login": "https://platform.openai.com/login",
        "keys": "https://platform.openai.com/api-keys",
        "signup": "https://platform.openai.com/signup",
    },
    "deepseek": {
        "login": "https://platform.deepseek.com/sign_in",
        "keys": "https://platform.deepseek.com/api_keys",
        "signup": "https://platform.deepseek.com/sign_up",
    },
    "gemini": {
        "login": "https://aistudio.google.com",
        "keys": "https://aistudio.google.com/apikey",
        "signup": "https://aistudio.google.com",
    },
}

# CLI tools that support native login flows
CLI_LOGIN_COMMANDS: dict[str, list[list[str]]] = {
    "anthropic": [["claude", "login"]],
    "openai": [["codex", "--login"]],
    "gemini": [["gemini", "auth", "login"], ["gcloud", "auth", "login"]],
}

# Display order and provider metadata for the wizard menu
PROVIDER_DISPLAY: list[dict[str, Any]] = [
    {
        "key": "anthropic",
        "label": "Claude (Anthropic)",
        "desc": "Claude Sonnet/Opus — best for agentic coding with MCP",
        "agent_cli": "claude",
        "auth_methods": ["cli_login", "browser_login", "api_key"],
    },
    {
        "key": "openai",
        "label": "Codex / OpenAI",
        "desc": "GPT-4o — OpenAI models via Codex CLI or API",
        "agent_cli": "codex",
        "auth_methods": ["cli_login", "browser_login", "api_key"],
    },
    {
        "key": "deepseek",
        "label": "DeepSeek",
        "desc": "DeepSeek-Chat — cost-effective reasoning model",
        "agent_cli": None,
        "auth_methods": ["browser_login", "api_key"],
    },
    {
        "key": "gemini",
        "label": "Google Gemini",
        "desc": "Gemini 2.5 Flash — Google's multimodal model",
        "agent_cli": "gemini",
        "auth_methods": ["cli_login", "browser_login", "api_key"],
    },
]


@dataclass
class WizardResult:
    """Result of running the setup wizard."""
    provider: str
    model: str
    auth_method: str  # "cli_login", "browser_login", "api_key", "env"
    key_validated: bool
    config_written: bool
    mcp_configured: bool
    project_bootstrapped: bool
    files_written: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _prompt(message: str, default: str = "") -> str:
    """Prompt the user for input with an optional default."""
    if default:
        raw = input(f"{message} [{default}]: ").strip()
        return raw or default
    return input(f"{message}: ").strip()


def _confirm(message: str, default: bool = True) -> bool:
    """Ask a yes/no question."""
    suffix = " [Y/n]: " if default else " [y/N]: "
    raw = input(f"{message}{suffix}").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes")


def _select_provider() -> str | None:
    """Display provider menu and return chosen key."""
    print("\n  Available LLM providers:\n")
    for i, p in enumerate(PROVIDER_DISPLAY, 1):
        print(f"    {i}) {p['label']}")
        print(f"       {p['desc']}")
    print()
    raw = _prompt("  Select provider (1-4)", "1")
    try:
        idx = int(raw) - 1
        if 0 <= idx < len(PROVIDER_DISPLAY):
            return PROVIDER_DISPLAY[idx]["key"]
    except ValueError:
        # Try matching by name
        raw_lower = raw.lower()
        for p in PROVIDER_DISPLAY:
            if raw_lower in (p["key"], p["label"].lower()):
                return p["key"]
    return None


def _detect_cli_login(provider: str) -> list[str] | None:
    """Check if a CLI login command is available for this provider.

    Returns the command list if the CLI tool is installed, else None.
    """
    commands = CLI_LOGIN_COMMANDS.get(provider, [])
    for cmd in commands:
        if shutil.which(cmd[0]):
            return cmd
    return None


def _run_cli_login(cmd: list[str]) -> bool:
    """Run a CLI login command interactively.

    Returns True if the command succeeded.
    """
    tool_name = cmd[0]
    print(f"\n  Launching {tool_name} login...")
    print(f"  Running: {' '.join(cmd)}")
    print()
    try:
        result = subprocess.run(
            cmd,
            timeout=300,  # 5 min timeout for interactive login
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"\n  Login timed out after 5 minutes.")
        return False
    except FileNotFoundError:
        print(f"\n  {tool_name} not found on PATH.")
        return False
    except Exception as exc:
        print(f"\n  Login failed: {exc}")
        return False


def _run_browser_login(provider: str) -> tuple[str, str]:
    """Open the provider's login page in the browser and wait for key entry.

    The flow:
    1. Open the provider's login page
    2. After login, redirect to the API keys page
    3. User copies their key and pastes it back

    Returns (api_key, auth_method).
    """
    urls = AUTH_URLS.get(provider, {})
    config = resolve_provider(provider)

    print(f"\n  ── {config['name']} Login ──")
    print()

    # Check if already logged in via env
    existing = os.environ.get(config["env_key"])
    if existing:
        masked = existing[:8] + "..." + existing[-4:] if len(existing) > 16 else "***"
        print(f"  Found existing credentials: {masked}")
        if _confirm("  Use existing credentials?"):
            return existing, "env"

    # Open login page
    login_url = urls.get("login", "")
    keys_url = urls.get("keys", "")

    print(f"  Opening {config['name']} login in your browser...")
    print()

    if login_url:
        webbrowser.open(login_url)

    print("  Complete these steps in your browser:")
    print(f"    1. Log in (or sign up) at the page that just opened")
    if keys_url != login_url:
        print(f"    2. Navigate to API keys: {keys_url}")
    else:
        print(f"    2. Go to API keys after logging in")
    print(f"    3. Create a new API key")
    print(f"    4. Copy the key and paste it below")
    print()

    # Wait a moment for the browser to open, then prompt
    api_key = _prompt(f"  Paste your {config['name']} API key here")
    if not api_key:
        return "", "browser_login"
    return api_key, "browser_login"


def _select_auth_method(provider: str) -> str:
    """Let the user choose their preferred authentication method."""
    display = next(
        (p for p in PROVIDER_DISPLAY if p["key"] == provider), None,
    )
    if not display:
        return "api_key"

    methods = display.get("auth_methods", ["api_key"])
    cli_cmd = _detect_cli_login(provider)
    config = resolve_provider(provider)

    # If CLI login is available, offer it first
    available: list[tuple[str, str]] = []

    if "cli_login" in methods and cli_cmd:
        tool = cli_cmd[0]
        available.append(("cli_login", f"Login with {tool} CLI (recommended)"))

    available.append(("browser_login", f"Login via browser ({config['name']} website)"))
    available.append(("api_key", "Enter API key manually"))

    if len(available) == 1:
        return available[0][0]

    print(f"\n  How would you like to authenticate with {config['name']}?\n")
    for i, (_, desc) in enumerate(available, 1):
        print(f"    {i}) {desc}")
    print()

    raw = _prompt("  Choose auth method", "1")
    try:
        idx = int(raw) - 1
        if 0 <= idx < len(available):
            return available[idx][0]
    except ValueError:
        pass
    return available[0][0]


def _get_api_key_manual(provider: str) -> tuple[str, str]:
    """Fallback: prompt for API key directly."""
    config = resolve_provider(provider)
    env_key = config["env_key"]

    existing = os.environ.get(env_key)
    if existing:
        masked = existing[:8] + "..." + existing[-4:] if len(existing) > 16 else "***"
        print(f"\n  Found {env_key} in environment: {masked}")
        if _confirm("  Use this key?"):
            return existing, "env"

    key = _prompt(f"\n  Enter your {config['name']} API key")
    return key, "api_key"


def _authenticate(provider: str) -> tuple[str, str]:
    """Run the authentication flow for a provider.

    Returns (api_key, auth_method).
    """
    method = _select_auth_method(provider)

    if method == "cli_login":
        cli_cmd = _detect_cli_login(provider)
        if cli_cmd and _run_cli_login(cli_cmd):
            # After CLI login, check if the key is now in env
            config = resolve_provider(provider)
            key = os.environ.get(config["env_key"], "")
            if key:
                return key, "cli_login"
            # CLI login succeeded but key not in env — user may need
            # to separately get an API key for hx's direct LLM calls
            print(f"\n  {cli_cmd[0]} login succeeded!")
            print(f"  For hx direct agent mode, you also need an API key.")
            return _run_browser_login(provider)
        else:
            print("\n  CLI login was not completed. Falling back to browser login.")
            return _run_browser_login(provider)

    if method == "browser_login":
        return _run_browser_login(provider)

    return _get_api_key_manual(provider)


def validate_api_key(provider: str, api_key: str) -> tuple[bool, str]:
    """Validate an API key by making a minimal API call.

    Returns (success, message).
    """
    config = resolve_provider(provider)

    if provider == "anthropic":
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=10,
                messages=[{"role": "user", "content": "Say 'ok'"}],
            )
            return True, "Key validated successfully"
        except ImportError:
            return True, "Key accepted (anthropic package not installed for validation)"
        except Exception as exc:
            msg = str(exc)
            if "401" in msg or "authentication" in msg.lower() or "invalid" in msg.lower():
                return False, f"Invalid API key: {msg}"
            return True, f"Key accepted (could not reach API: {msg})"
    else:
        try:
            import openai
            client = openai.OpenAI(
                api_key=api_key,
                base_url=config.get("base_url"),
            )
            client.models.list()
            return True, "Key validated successfully"
        except ImportError:
            return True, "Key accepted (openai package not installed for validation)"
        except Exception as exc:
            msg = str(exc)
            if "401" in msg or "authentication" in msg.lower() or "invalid" in msg.lower():
                return False, f"Invalid API key: {msg}"
            return True, f"Key accepted (could not reach API: {msg})"


def _write_provider_config(
    root: Path,
    provider: str,
    model: str,
    env_key: str,
    auth_method: str,
) -> bool:
    """Write provider configuration to .hx/provider.toml."""
    config_path = root / PROVIDER_CONFIG_FILE
    config_path.parent.mkdir(parents=True, exist_ok=True)
    content = f"""# hx provider configuration
# Generated by `hx provider setup`

provider = "{provider}"
model = "{model}"
env_key = "{env_key}"
auth_method = "{auth_method}"

# To change providers, run `hx provider setup` again
# API keys are read from environment variables — never stored in this file
"""
    config_path.write_text(content)
    return True


def load_provider_config(root: Path) -> dict[str, str] | None:
    """Load provider config from .hx/provider.toml if it exists."""
    config_path = root / PROVIDER_CONFIG_FILE
    if not config_path.exists():
        return None
    # Simple TOML key=value parser (avoids tomllib dependency for Python 3.10)
    result: dict[str, str] = {}
    for line in config_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            result[key] = value
    return result if result else None


def _setup_mcp_integration(
    root: Path, provider: str,
) -> tuple[bool, list[str]]:
    """Configure MCP integration for the provider's agent CLI."""
    files: list[str] = []
    display = next(
        (p for p in PROVIDER_DISPLAY if p["key"] == provider), None,
    )
    if not display:
        return False, files

    agent_cli = display.get("agent_cli")

    # Claude Code: bootstrap generates .claude/ configs
    if provider == "anthropic":
        from hx.bootstrap import run_bootstrap
        result = run_bootstrap(root, language="unknown")
        if "error" not in result:
            files.extend(result.get("files_written", []))
            return True, files
        return False, files

    # Codex: write MCP config
    if agent_cli == "codex":
        from hx.codex_integration import install_codex_config
        status = install_codex_config(root)
        files.append(str(status.config_path))
        from hx.bootstrap import run_bootstrap
        result = run_bootstrap(root, language="unknown")
        if "error" not in result:
            files.extend(result.get("files_written", []))
        return True, files

    # Gemini: write MCP config
    if agent_cli == "gemini":
        from hx.gemini_integration import install_gemini_config
        status = install_gemini_config(root)
        files.append(str(status.config_path))
        from hx.bootstrap import run_bootstrap
        result = run_bootstrap(root, language="unknown")
        if "error" not in result:
            files.extend(result.get("files_written", []))
        return True, files

    # DeepSeek: no dedicated CLI, just bootstrap
    from hx.bootstrap import run_bootstrap
    result = run_bootstrap(root, language="unknown")
    if "error" not in result:
        files.extend(result.get("files_written", []))
        return True, files
    return False, files


def _write_env_hint(root: Path, env_key: str) -> str | None:
    """Write a .env.hx hint file (key NOT stored — just the var name)."""
    env_path = root / ".env.hx"
    lines = []
    if env_path.exists():
        lines = env_path.read_text().splitlines()

    prefix = f"{env_key}="
    for line in lines:
        if line.startswith(prefix):
            return None

    lines.append(f"# Set this in your shell: export {env_key}='your-key'")
    lines.append(f"{env_key}=")
    lines.append("")
    env_path.write_text("\n".join(lines))
    return ".env.hx"


def run_wizard(
    root: Path,
    *,
    provider: str | None = None,
    skip_validation: bool = False,
    skip_mcp: bool = False,
    skip_scaffold: bool = False,
    non_interactive: bool = False,
) -> WizardResult:
    """Run the interactive setup wizard.

    The default flow is login-first: the wizard opens the provider's
    login page in the browser (or runs their CLI login command) rather
    than asking for a raw API key. API key entry is available as a
    fallback.

    Args:
        root: Repository root path.
        provider: Pre-selected provider (skips selection menu).
        skip_validation: Skip API key validation.
        skip_mcp: Skip MCP integration setup.
        skip_scaffold: Skip project scaffolding.
        non_interactive: Run without prompts (requires provider and env key).
    """
    result = WizardResult(
        provider="",
        model="",
        auth_method="",
        key_validated=False,
        config_written=False,
        mcp_configured=False,
        project_bootstrapped=False,
    )

    # Step 1: Select provider
    if provider:
        try:
            resolve_provider(provider)
        except ValueError:
            result.errors.append(f"Unknown provider: {provider}")
            return result
        chosen = provider
    elif non_interactive:
        result.errors.append("--provider required in non-interactive mode")
        return result
    else:
        print("\n  ── hx provider setup wizard ──")
        print("  Connect your AI provider to start building with hx.\n")
        chosen = _select_provider()
        if not chosen:
            result.errors.append("No provider selected")
            return result

    config = resolve_provider(chosen)
    result.provider = chosen
    result.model = config["default_model"]

    # Step 2: Authenticate (login-first)
    if non_interactive:
        api_key = os.environ.get(config["env_key"], "")
        auth_method = "env" if api_key else ""
        if not api_key:
            result.errors.append(
                f"{config['env_key']} not set in environment"
            )
            return result
    else:
        api_key, auth_method = _authenticate(chosen)
        if not api_key:
            result.errors.append(
                "Authentication was not completed. "
                "Run `hx provider setup` to try again."
            )
            return result

    result.auth_method = auth_method

    # Step 3: Model selection
    if not non_interactive:
        model = _prompt(
            f"\n  Model to use", config["default_model"],
        )
        result.model = model

    # Step 4: Validate credentials
    if not skip_validation:
        if not non_interactive:
            print("\n  Validating credentials...")
        ok, msg = validate_api_key(chosen, api_key)
        result.key_validated = ok
        if not ok:
            result.errors.append(msg)
            if not non_interactive:
                print(f"  ✗ {msg}")
                if not _confirm("  Continue anyway?", default=False):
                    return result
                result.errors.clear()  # User chose to continue
            else:
                return result
        elif not non_interactive:
            print(f"  ✓ {msg}")
    else:
        result.key_validated = True

    # Step 5: Set environment variable for current session
    if auth_method in ("browser_login", "api_key"):
        os.environ[config["env_key"]] = api_key
        if not non_interactive:
            print(f"\n  Set {config['env_key']} for this session.")
            print(f"  To persist, add to your shell profile:")
            print(f"    export {config['env_key']}='{api_key[:8]}...'")

    # Step 6: Write provider config
    _write_provider_config(
        root, chosen, result.model, config["env_key"], auth_method,
    )
    result.config_written = True
    result.files_written.append(PROVIDER_CONFIG_FILE)

    # Step 7: Write env hint file
    hint = _write_env_hint(root, config["env_key"])
    if hint:
        result.files_written.append(hint)

    # Step 8: Project scaffolding
    if not skip_scaffold:
        from hx.setup import run_setup
        if not non_interactive:
            should_scaffold = _confirm(
                "\n  Run project scaffolding (hx setup)?",
            )
        else:
            should_scaffold = True

        if should_scaffold:
            setup_result = run_setup(root)
            result.project_bootstrapped = True
            result.files_written.extend(setup_result.get("files_written", []))

    # Step 9: MCP integration
    if not skip_mcp:
        if not non_interactive:
            should_mcp = _confirm(
                "  Configure MCP integration for agent CLI?",
            )
        else:
            should_mcp = True

        if should_mcp:
            ok, files = _setup_mcp_integration(root, chosen)
            result.mcp_configured = ok
            result.files_written.extend(files)

    # Deduplicate files list
    result.files_written = list(dict.fromkeys(result.files_written))

    return result


def render_wizard_result(result: WizardResult, *, color: bool = False) -> str:
    """Render the wizard result as a terminal-friendly string."""
    from hx.ui import paint

    lines: list[str] = []

    if result.errors:
        lines.append(paint("Setup failed:", "red", color=color))
        for err in result.errors:
            lines.append(f"  ✗ {err}")
        return "\n".join(lines)

    config = resolve_provider(result.provider)
    lines.append("")
    lines.append(paint("  ── hx provider setup complete ──", "bold", "green", color=color))
    lines.append("")
    lines.append(f"  Provider:    {config['name']}")
    lines.append(f"  Model:       {result.model}")
    lines.append(f"  Logged in:   {_auth_method_label(result.auth_method)}")
    lines.append(f"  Validated:   {'yes' if result.key_validated else 'no'}")
    lines.append("")

    if result.files_written:
        lines.append(paint("  Files written:", "bold", color=color))
        for f in result.files_written:
            lines.append(f"    + {f}")
        lines.append("")

    if result.warnings:
        for w in result.warnings:
            lines.append(paint(f"  ⚠ {w}", "yellow", color=color))
        lines.append("")

    # Next steps
    lines.append(paint("  Next steps:", "bold", color=color))

    display = next(
        (p for p in PROVIDER_DISPLAY if p["key"] == result.provider), None,
    )
    agent_cli = display["agent_cli"] if display else None

    steps = []
    if result.auth_method in ("browser_login", "api_key"):
        steps.append(
            f"Add `export {config['env_key']}='...'` to your shell profile to persist"
        )
    if not result.project_bootstrapped:
        steps.append("Run `hx setup` to scaffold project governance files")
    if not result.mcp_configured and agent_cli:
        steps.append(f"Run `hx {agent_cli} setup` to configure MCP")

    steps.append(f"Run `hx run '<task>' --provider {result.provider}` to start")

    if result.provider == "anthropic" and agent_cli:
        steps.append("Or launch `claude` in this repo — hx MCP auto-connects")
    elif agent_cli == "codex":
        steps.append("Or run `codex` in this repo — hx MCP auto-connects")
    elif agent_cli == "gemini":
        steps.append("Or run `gemini` in this repo — hx MCP auto-connects")

    for i, step in enumerate(steps, 1):
        lines.append(f"    {i}. {step}")

    lines.append("")
    return "\n".join(lines)


def _auth_method_label(method: str) -> str:
    """Human-readable label for an auth method."""
    return {
        "cli_login": "via CLI login",
        "browser_login": "via browser login",
        "api_key": "via API key",
        "env": "from environment",
    }.get(method, method)


def provider_status(root: Path) -> dict[str, Any]:
    """Return structured status of all configured providers."""
    statuses: list[dict[str, Any]] = []
    active_config = load_provider_config(root)
    active_provider = active_config.get("provider") if active_config else None

    for key, config in PROVIDERS.items():
        env_val = os.environ.get(config["env_key"])
        cli_cmd = _detect_cli_login(key)
        statuses.append({
            "provider": key,
            "name": config["name"],
            "env_key": config["env_key"],
            "key_set": bool(env_val),
            "cli_available": cli_cmd is not None,
            "cli_tool": cli_cmd[0] if cli_cmd else None,
            "active": key == active_provider,
            "auth_method": (
                active_config.get("auth_method", "unknown")
                if key == active_provider else None
            ),
            "model": (
                active_config.get("model", config["default_model"])
                if key == active_provider
                else config["default_model"]
            ),
        })

    return {
        "active_provider": active_provider,
        "config_file": str(root / PROVIDER_CONFIG_FILE),
        "config_exists": (root / PROVIDER_CONFIG_FILE).exists(),
        "providers": statuses,
    }


def render_provider_status(
    status: dict[str, Any], *, color: bool = False,
) -> str:
    """Render provider status for terminal display."""
    from hx.ui import paint

    lines: list[str] = []
    lines.append(paint("hx provider status", "bold", "blue", color=color))
    lines.append(paint("─" * 50, "dim", color=color))

    active = status.get("active_provider")
    if active:
        lines.append(f"Active provider: {active}")
    else:
        lines.append("Active provider: none (run `hx provider setup`)")
    lines.append("")

    for p in status["providers"]:
        if p["active"]:
            marker = paint("●", "green", color=color)
        elif p["key_set"]:
            marker = paint("○", "yellow", color=color)
        else:
            marker = paint("·", "dim", color=color)

        key_status = (
            paint("authenticated", "green", color=color)
            if p["key_set"]
            else paint("not logged in", "red", color=color)
        )

        lines.append(f"  {marker} {p['name']}")
        lines.append(f"    status: {key_status}")
        if p["auth_method"]:
            lines.append(f"    auth: {_auth_method_label(p['auth_method'])}")
        if p["cli_available"]:
            lines.append(
                paint(f"    cli: {p['cli_tool']} (available)", "dim", color=color)
            )
        lines.append(f"    model: {p['model']}")

    lines.append("")
    if not active:
        lines.append("Run `hx provider setup` to log in and configure a provider.")
    elif not any(p["key_set"] for p in status["providers"] if p["active"]):
        lines.append("Run `hx provider setup` to re-authenticate.")

    return "\n".join(lines)
