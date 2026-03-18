"""LLM provider abstraction for multi-provider agent loop.

Supports Anthropic (Claude), OpenAI-compatible (GPT, DeepSeek), and
Google Gemini. The governance layer is provider-independent — only the
LLM call changes.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

PROVIDERS = {
    "anthropic": {
        "name": "Anthropic (Claude)",
        "env_key": "ANTHROPIC_API_KEY",
        "default_model": "claude-sonnet-4-20250514",
        "package": "anthropic",
    },
    "openai": {
        "name": "OpenAI (GPT)",
        "env_key": "OPENAI_API_KEY",
        "default_model": "gpt-4o",
        "package": "openai",
    },
    "deepseek": {
        "name": "DeepSeek",
        "env_key": "DEEPSEEK_API_KEY",
        "default_model": "deepseek-chat",
        "package": "openai",
        "base_url": "https://api.deepseek.com",
    },
    "gemini": {
        "name": "Google Gemini",
        "env_key": "GEMINI_API_KEY",
        "default_model": "gemini-2.5-flash",
        "package": "openai",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
    },
}


@dataclass
class LLMResponse:
    """Unified response from any provider."""
    text: str
    tool_calls: list[dict[str, Any]]
    raw: Any = None


def resolve_provider(provider: str) -> dict[str, Any]:
    """Get provider config, raising ValueError for unknown providers."""
    if provider not in PROVIDERS:
        available = ", ".join(sorted(PROVIDERS.keys()))
        raise ValueError(
            f"Unknown provider '{provider}'. "
            f"Available: {available}"
        )
    return PROVIDERS[provider]


def resolve_api_key(provider: str) -> str | None:
    """Get the API key for a provider from environment."""
    config = resolve_provider(provider)
    return os.environ.get(config["env_key"])


def openai_tool_schemas(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert hx tool schemas to OpenAI function-calling format."""
    converted = []
    for tool in tools:
        converted.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["input_schema"],
            },
        })
    return converted


def call_anthropic(
    api_key: str,
    model: str,
    system_prompt: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    *,
    max_tokens: int = 8192,
    renderer: Any = None,
) -> LLMResponse:
    """Call Anthropic Claude API with streaming."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)

    with client.messages.stream(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=messages,
        tools=tools,
    ) as stream:
        current_text = ""
        for event in stream:
            if event.type == "content_block_delta":
                if event.delta.type == "text_delta":
                    if renderer:
                        renderer.text_delta(event.delta.text)
                    current_text += event.delta.text
        if renderer:
            renderer.text_done()

        final = stream.get_final_message()

    text_parts = []
    tool_calls = []
    assistant_content = []

    for block in final.content:
        if block.type == "text":
            text_parts.append(block.text)
            assistant_content.append({
                "type": "text", "text": block.text,
            })
        elif block.type == "tool_use":
            tool_calls.append({
                "id": block.id,
                "name": block.name,
                "input": block.input,
            })
            assistant_content.append({
                "type": "tool_use",
                "id": block.id,
                "name": block.name,
                "input": block.input,
            })

    return LLMResponse(
        text="\n".join(text_parts),
        tool_calls=tool_calls,
        raw={"assistant_content": assistant_content},
    )


def call_openai_compatible(
    api_key: str,
    model: str,
    system_prompt: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    *,
    base_url: str | None = None,
    max_tokens: int = 8192,
    renderer: Any = None,
) -> LLMResponse:
    """Call OpenAI-compatible API (OpenAI, DeepSeek, Gemini)."""
    try:
        import openai
    except ImportError as exc:
        raise ImportError(
            "openai package required for this provider. "
            "Run: pip install openai"
        ) from exc

    client = openai.OpenAI(api_key=api_key, base_url=base_url)

    # Convert messages: Anthropic format -> OpenAI format
    oai_messages = [{"role": "system", "content": system_prompt}]
    for msg in messages:
        if msg["role"] == "user":
            content = msg["content"]
            if isinstance(content, str):
                oai_messages.append({"role": "user", "content": content})
            elif isinstance(content, list):
                # Tool results
                for item in content:
                    if item.get("type") == "tool_result":
                        oai_messages.append({
                            "role": "tool",
                            "tool_call_id": item["tool_use_id"],
                            "content": item.get("content", ""),
                        })
        elif msg["role"] == "assistant":
            content = msg["content"]
            if isinstance(content, str):
                oai_messages.append({
                    "role": "assistant", "content": content,
                })
            elif isinstance(content, list):
                text_parts = []
                oai_tool_calls = []
                for block in content:
                    if block.get("type") == "text":
                        text_parts.append(block["text"])
                    elif block.get("type") == "tool_use":
                        oai_tool_calls.append({
                            "id": block["id"],
                            "type": "function",
                            "function": {
                                "name": block["name"],
                                "arguments": json.dumps(block["input"]),
                            },
                        })
                msg_dict: dict[str, Any] = {
                    "role": "assistant",
                    "content": "\n".join(text_parts) or None,
                }
                if oai_tool_calls:
                    msg_dict["tool_calls"] = oai_tool_calls
                oai_messages.append(msg_dict)

    oai_tools = openai_tool_schemas(tools)

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": oai_messages,
        "max_tokens": max_tokens,
    }
    if oai_tools:
        kwargs["tools"] = oai_tools

    response = client.chat.completions.create(**kwargs)
    choice = response.choices[0]
    message = choice.message

    text = message.content or ""
    if renderer and text:
        renderer.text_delta(text)
        renderer.text_done()

    tool_calls = []
    assistant_content: list[dict[str, Any]] = []

    if text:
        assistant_content.append({"type": "text", "text": text})

    if message.tool_calls:
        for tc in message.tool_calls:
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}
            tool_calls.append({
                "id": tc.id,
                "name": tc.function.name,
                "input": args,
            })
            assistant_content.append({
                "type": "tool_use",
                "id": tc.id,
                "name": tc.function.name,
                "input": args,
            })

    return LLMResponse(
        text=text,
        tool_calls=tool_calls,
        raw={"assistant_content": assistant_content},
    )


def call_llm(
    provider: str,
    api_key: str,
    model: str,
    system_prompt: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    *,
    max_tokens: int = 8192,
    renderer: Any = None,
) -> LLMResponse:
    """Unified LLM call — dispatches to the right provider."""
    config = resolve_provider(provider)

    if provider == "anthropic":
        return call_anthropic(
            api_key, model, system_prompt, messages, tools,
            max_tokens=max_tokens, renderer=renderer,
        )
    else:
        return call_openai_compatible(
            api_key, model, system_prompt, messages, tools,
            base_url=config.get("base_url"),
            max_tokens=max_tokens, renderer=renderer,
        )
