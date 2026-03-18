"""Tests for multi-provider LLM abstraction."""
from __future__ import annotations

import pytest

from hx.providers import (
    PROVIDERS,
    LLMResponse,
    openai_tool_schemas,
    resolve_api_key,
    resolve_provider,
)


class TestProviderConfig:
    def test_all_providers_have_required_keys(self) -> None:
        for name, config in PROVIDERS.items():
            assert "name" in config, f"{name} missing 'name'"
            assert "env_key" in config, f"{name} missing 'env_key'"
            assert "default_model" in config, f"{name} missing 'default_model'"
            assert "package" in config, f"{name} missing 'package'"

    def test_resolve_known_provider(self) -> None:
        config = resolve_provider("anthropic")
        assert config["name"] == "Anthropic (Claude)"
        assert config["env_key"] == "ANTHROPIC_API_KEY"

    def test_resolve_deepseek(self) -> None:
        config = resolve_provider("deepseek")
        assert config["name"] == "DeepSeek"
        assert "base_url" in config

    def test_resolve_gemini(self) -> None:
        config = resolve_provider("gemini")
        assert config["name"] == "Google Gemini"
        assert "base_url" in config

    def test_resolve_unknown_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown provider"):
            resolve_provider("nonexistent")

    def test_resolve_api_key_missing(self, monkeypatch: object) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert resolve_api_key("anthropic") is None

    def test_resolve_api_key_present(self, monkeypatch: object) -> None:
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
        assert resolve_api_key("deepseek") == "test-key"


class TestToolSchemaConversion:
    def test_openai_format(self) -> None:
        anthropic_tools = [
            {
                "name": "hex_resolve_cell",
                "description": "Resolve a file path to cell_id.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                    },
                    "required": ["path"],
                },
            },
        ]
        oai = openai_tool_schemas(anthropic_tools)
        assert len(oai) == 1
        assert oai[0]["type"] == "function"
        assert oai[0]["function"]["name"] == "hex_resolve_cell"
        assert "parameters" in oai[0]["function"]

    def test_preserves_all_tools(self) -> None:
        tools = [
            {"name": f"tool_{i}", "description": f"Tool {i}",
             "input_schema": {"type": "object", "properties": {}}}
            for i in range(5)
        ]
        oai = openai_tool_schemas(tools)
        assert len(oai) == 5


class TestLLMResponse:
    def test_response_structure(self) -> None:
        resp = LLMResponse(
            text="hello",
            tool_calls=[{"id": "1", "name": "test", "input": {}}],
        )
        assert resp.text == "hello"
        assert len(resp.tool_calls) == 1
        assert resp.raw is None

    def test_empty_response(self) -> None:
        resp = LLMResponse(text="", tool_calls=[])
        assert resp.text == ""
        assert resp.tool_calls == []


class TestProviderCount:
    def test_four_providers(self) -> None:
        assert len(PROVIDERS) == 4
        assert "anthropic" in PROVIDERS
        assert "openai" in PROVIDERS
        assert "deepseek" in PROVIDERS
        assert "gemini" in PROVIDERS
