"""Tests for the unified provider setup wizard."""
from __future__ import annotations

import subprocess
from pathlib import Path

from hx.providers import PROVIDERS
from hx.wizard import (
    AUTH_URLS,
    CLI_LOGIN_COMMANDS,
    PROVIDER_CONFIG_FILE,
    PROVIDER_DISPLAY,
    WizardResult,
    _auth_method_label,
    _detect_cli_login,
    load_provider_config,
    provider_status,
    render_provider_status,
    render_wizard_result,
    run_wizard,
    validate_api_key,
)


def _git_init(tmp_path: Path) -> None:
    subprocess.run(
        ["git", "init"], cwd=tmp_path, check=True, capture_output=True,
    )


def _scaffold_repo(tmp_path: Path) -> None:
    """Create a minimal repo structure for wizard tests."""
    _git_init(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hello')\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("def test_a(): pass\n")


class TestProviderDisplay:
    def test_all_providers_have_display_entry(self) -> None:
        display_keys = {p["key"] for p in PROVIDER_DISPLAY}
        assert display_keys == set(PROVIDERS.keys())

    def test_display_entries_have_required_fields(self) -> None:
        for entry in PROVIDER_DISPLAY:
            assert "key" in entry
            assert "label" in entry
            assert "desc" in entry
            assert "agent_cli" in entry
            assert "auth_methods" in entry

    def test_all_display_entries_have_browser_login(self) -> None:
        """Every provider must support browser login as the primary flow."""
        for entry in PROVIDER_DISPLAY:
            assert "browser_login" in entry["auth_methods"], (
                f"{entry['key']} must support browser_login"
            )


class TestAuthUrls:
    def test_all_providers_have_auth_urls(self) -> None:
        for key in PROVIDERS:
            assert key in AUTH_URLS, f"{key} missing from AUTH_URLS"

    def test_auth_urls_have_login_and_keys(self) -> None:
        for key, urls in AUTH_URLS.items():
            assert "login" in urls, f"{key} missing 'login' URL"
            assert "keys" in urls, f"{key} missing 'keys' URL"


class TestCliLoginDetection:
    def test_returns_none_for_missing_cli(self) -> None:
        # deepseek has no CLI login — should always return None
        # (unless someone installs a deepseek CLI, which is unlikely)
        result = _detect_cli_login("nonexistent_provider")
        assert result is None

    def test_returns_list_for_known_provider(self) -> None:
        """CLI_LOGIN_COMMANDS has entries for providers with CLI tools."""
        for provider in CLI_LOGIN_COMMANDS:
            assert provider in PROVIDERS


class TestAuthMethodLabel:
    def test_known_methods(self) -> None:
        assert "CLI" in _auth_method_label("cli_login")
        assert "browser" in _auth_method_label("browser_login")
        assert "API" in _auth_method_label("api_key")
        assert "environment" in _auth_method_label("env")

    def test_unknown_method(self) -> None:
        assert _auth_method_label("custom") == "custom"


class TestLoadProviderConfig:
    def test_returns_none_when_missing(self, tmp_path: Path) -> None:
        assert load_provider_config(tmp_path) is None

    def test_loads_valid_config(self, tmp_path: Path) -> None:
        config_path = tmp_path / PROVIDER_CONFIG_FILE
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            'provider = "anthropic"\n'
            'model = "claude-sonnet-4-20250514"\n'
            'env_key = "ANTHROPIC_API_KEY"\n'
            'auth_method = "browser_login"\n'
        )
        config = load_provider_config(tmp_path)
        assert config is not None
        assert config["provider"] == "anthropic"
        assert config["auth_method"] == "browser_login"

    def test_ignores_comments(self, tmp_path: Path) -> None:
        config_path = tmp_path / PROVIDER_CONFIG_FILE
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            "# This is a comment\n"
            'provider = "deepseek"\n'
        )
        config = load_provider_config(tmp_path)
        assert config is not None
        assert config["provider"] == "deepseek"


class TestProviderStatus:
    def test_status_lists_all_providers(self, tmp_path: Path) -> None:
        status = provider_status(tmp_path)
        provider_keys = {p["provider"] for p in status["providers"]}
        assert provider_keys == set(PROVIDERS.keys())

    def test_no_active_when_unconfigured(self, tmp_path: Path) -> None:
        status = provider_status(tmp_path)
        assert status["active_provider"] is None
        assert not status["config_exists"]

    def test_active_when_configured(self, tmp_path: Path) -> None:
        config_path = tmp_path / PROVIDER_CONFIG_FILE
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            'provider = "gemini"\n'
            'model = "gemini-2.5-flash"\n'
            'env_key = "GEMINI_API_KEY"\n'
            'auth_method = "browser_login"\n'
        )
        status = provider_status(tmp_path)
        assert status["active_provider"] == "gemini"
        assert status["config_exists"]
        active = next(p for p in status["providers"] if p["active"])
        assert active["provider"] == "gemini"
        assert active["auth_method"] == "browser_login"

    def test_key_set_detection(self, tmp_path: Path, monkeypatch: object) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        status = provider_status(tmp_path)
        anthropic = next(p for p in status["providers"] if p["provider"] == "anthropic")
        openai = next(p for p in status["providers"] if p["provider"] == "openai")
        assert anthropic["key_set"] is True
        assert openai["key_set"] is False

    def test_status_includes_cli_info(self, tmp_path: Path) -> None:
        status = provider_status(tmp_path)
        for p in status["providers"]:
            assert "cli_available" in p
            assert "cli_tool" in p


class TestRenderProviderStatus:
    def test_renders_without_error(self, tmp_path: Path) -> None:
        status = provider_status(tmp_path)
        output = render_provider_status(status)
        assert "hx provider status" in output
        assert "Active provider:" in output

    def test_shows_login_language(self, tmp_path: Path) -> None:
        status = provider_status(tmp_path)
        output = render_provider_status(status)
        assert "not logged in" in output

    def test_renders_with_color(self, tmp_path: Path) -> None:
        status = provider_status(tmp_path)
        output = render_provider_status(status, color=True)
        assert "\033[" in output


class TestWizardResult:
    def test_default_fields(self) -> None:
        result = WizardResult(
            provider="anthropic",
            model="claude-sonnet-4-20250514",
            auth_method="browser_login",
            key_validated=True,
            config_written=True,
            mcp_configured=False,
            project_bootstrapped=False,
        )
        assert result.files_written == []
        assert result.errors == []
        assert result.warnings == []


class TestRenderWizardResult:
    def test_renders_success(self) -> None:
        result = WizardResult(
            provider="anthropic",
            model="claude-sonnet-4-20250514",
            auth_method="browser_login",
            key_validated=True,
            config_written=True,
            mcp_configured=True,
            project_bootstrapped=True,
            files_written=[PROVIDER_CONFIG_FILE],
        )
        output = render_wizard_result(result)
        assert "Anthropic" in output
        assert "complete" in output
        assert "browser" in output.lower()

    def test_renders_cli_login(self) -> None:
        result = WizardResult(
            provider="openai",
            model="gpt-4o",
            auth_method="cli_login",
            key_validated=True,
            config_written=True,
            mcp_configured=True,
            project_bootstrapped=True,
        )
        output = render_wizard_result(result)
        assert "CLI" in output

    def test_renders_errors(self) -> None:
        result = WizardResult(
            provider="",
            model="",
            auth_method="",
            key_validated=False,
            config_written=False,
            mcp_configured=False,
            project_bootstrapped=False,
            errors=["Authentication was not completed."],
        )
        output = render_wizard_result(result)
        assert "failed" in output
        assert "not completed" in output


class TestRunWizardNonInteractive:
    def test_requires_provider(self, tmp_path: Path) -> None:
        result = run_wizard(tmp_path, non_interactive=True)
        assert len(result.errors) > 0
        assert "provider" in result.errors[0].lower()

    def test_requires_env_key(self, tmp_path: Path, monkeypatch: object) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        result = run_wizard(
            tmp_path, provider="anthropic", non_interactive=True,
        )
        assert len(result.errors) > 0
        assert "ANTHROPIC_API_KEY" in result.errors[0]

    def test_unknown_provider(self, tmp_path: Path) -> None:
        result = run_wizard(
            tmp_path, provider="nonexistent", non_interactive=True,
        )
        assert len(result.errors) > 0
        assert "Unknown" in result.errors[0]

    def test_full_non_interactive_flow(
        self, tmp_path: Path, monkeypatch: object,
    ) -> None:
        _scaffold_repo(tmp_path)
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key-12345")
        result = run_wizard(
            tmp_path,
            provider="deepseek",
            non_interactive=True,
            skip_validation=True,
            skip_mcp=True,
        )
        assert result.provider == "deepseek"
        assert result.auth_method == "env"
        assert result.config_written
        assert result.key_validated
        assert (tmp_path / PROVIDER_CONFIG_FILE).exists()

    def test_writes_provider_config_with_auth_method(
        self, tmp_path: Path, monkeypatch: object,
    ) -> None:
        _scaffold_repo(tmp_path)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
        result = run_wizard(
            tmp_path,
            provider="openai",
            non_interactive=True,
            skip_validation=True,
            skip_mcp=True,
            skip_scaffold=True,
        )
        assert result.config_written
        config = load_provider_config(tmp_path)
        assert config is not None
        assert config["provider"] == "openai"
        assert config["auth_method"] == "env"


class TestValidateApiKey:
    def test_validates_with_missing_package(self) -> None:
        ok, msg = validate_api_key("deepseek", "fake-key")
        assert isinstance(ok, bool)
        assert isinstance(msg, str)
