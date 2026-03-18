"""Agent loop: orchestrates an LLM with hx governance tools."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hx.audit import append_event, finish_run, start_run
from hx.authz import allowed_cells as calc_allowed_cells
from hx.config import ensure_hx_dirs
from hx.hexmap import adjacency_summary, load_hexmap
from hx.memory import load_memory_context
from hx.reasoning import (
    ReasoningMode,
    build_scoped_prompt,
    check_feedback_integrity,
    reasoning_gate,
)
from hx.stream import StreamRenderer
from hx.tools import ToolRegistry

# Max chars for compressed tool results (~3K tokens)
_MAX_RESULT_CHARS = 12_000


def _memory_section(root: Path) -> str:
    """Build an optional memory context section for the system prompt."""
    memory_block = load_memory_context(root)
    if not memory_block:
        return ""
    return f"""
## Memory Context
{memory_block}
"""


def _compress_tool_result(
    tool_name: str, result: dict[str, Any],
) -> dict[str, Any]:
    """Deduplicate and compact a tool result to reduce token usage."""
    compressed = dict(result)

    # Strip null ports from port-related results
    if "ports" in compressed and isinstance(compressed["ports"], list):
        compressed["ports"] = [
            p for p in compressed["ports"]
            if p.get("neighbor_cell_id") is not None
            or p.get("port_contract") is not None
        ]
        # Deduplicate identical port entries
        seen: set[str] = set()
        deduped = []
        for p in compressed["ports"]:
            key = json.dumps(p, sort_keys=True, default=str)
            if key not in seen:
                seen.add(key)
                deduped.append(p)
        compressed["ports"] = deduped

    # Strip verbose fields from port.check
    if tool_name == "port.check":
        risk = compressed.get("risk_summary", {})
        if "high_risk_ports" in risk:
            risk.pop("ports", None)
        risk.pop("reporting_note", None)
        obligations = compressed.get("obligations", {})
        obligations.pop("check_specs", None)
        obligations.pop("artifact_specs", None)

    # Truncate oversized results
    serialized = json.dumps(compressed, default=str)
    if len(serialized) > _MAX_RESULT_CHARS:
        compressed["_truncated"] = True
        compressed["_original_size"] = len(serialized)
        # Keep only top-level keys with compact values
        for key in list(compressed.keys()):
            val = json.dumps(compressed[key], default=str)
            if len(val) > 2000:
                if isinstance(compressed[key], list):
                    compressed[key] = compressed[key][:5]
                elif isinstance(compressed[key], dict):
                    compressed[key] = {
                        k: v for i, (k, v) in
                        enumerate(compressed[key].items()) if i < 10
                    }

    return compressed


def _build_system_prompt(
    registry: ToolRegistry,
    active_cell_id: str,
    radius: int,
) -> str:
    base = registry.root
    hexmap = load_hexmap(base)
    cell = hexmap.cell(active_cell_id)
    allowed = calc_allowed_cells(hexmap, active_cell_id, radius)

    # Sparse graph: direct hex graph query instead of 36 port.describe calls
    edges = adjacency_summary(hexmap, allowed)
    if edges:
        port_lines = [
            f"  {e['from']}[{e['side']}] -> {e['to']} ({e['direction']})"
            for e in edges[:12]
        ]
        ports_text = "\n".join(port_lines)
    else:
        ports_text = "  (no active ports)"

    return f"""You are an AI coding agent operating inside hx governance.

## Your Cell
- Active cell: {active_cell_id}
- Radius: R{radius}
- Summary: {cell.summary}
- Invariants: {', '.join(cell.invariants) or 'none'}
- Allowed cells: {', '.join(allowed)}

## Cell Graph
{ports_text}

## Governance Rules
- You may ONLY read/write files within your allowed cells.
- Use hex.context (default: summary mode) to explore, then detail='full' if needed.
- repo.read supports offset/limit for large files. Check total_lines first.
- repo.search returns max 20 results; use total_count to know if more exist.
- Use repo.stage_patch to propose changes as unified diffs.
- After staging, run port.check to detect boundary impacts.
- Run proof.collect and proof.verify before committing.
- Use repo.commit_patch to finalize.

## Important
- Prefer minimal radius. Justify any radius expansion.
- Every action is audited. Be precise and deliberate.
- active_cell_id="{active_cell_id}", radius={radius} — pass these to tools.
{_memory_section(base)}"""


def run_agent(
    root: Path,
    task_description: str,
    *,
    active_cell_id: str,
    radius: int,
    model: str | None = None,
    provider: str = "anthropic",
    max_turns: int = 50,
    color: bool = False,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Run the governed agent loop. Returns a summary dict.

    Supports multiple providers: anthropic, openai, deepseek, gemini.
    The governance layer is provider-independent.
    """
    from hx.providers import call_llm, resolve_api_key, resolve_provider

    try:
        config = resolve_provider(provider)
    except ValueError as exc:
        return {"status": "error", "error": str(exc)}

    effective_key = api_key or resolve_api_key(provider)
    if not effective_key:
        return {
            "status": "error",
            "error": (
                f"{config['env_key']} not set. "
                f"Set it to use {config['name']}."
            ),
        }

    effective_model = model or config["default_model"]

    ensure_hx_dirs(root)
    registry = ToolRegistry(root)
    renderer = StreamRenderer(color=color)

    renderer.session_start(active_cell_id, radius, task_description)

    # Start audit run
    audit_run = start_run(
        root, "hx.run",
        active_cell_id=active_cell_id,
        radius=radius,
        allowed=calc_allowed_cells(load_hexmap(root), active_cell_id, radius),
    )

    tools = registry.anthropic_tool_schemas()

    # Reasoning gate: decide LLM consultation strategy
    gate = reasoning_gate(root, active_cell_id, radius)
    gate_mode = gate["mode"]
    append_event(root, audit_run.run_id, "reasoning.gate", gate)

    if gate_mode == ReasoningMode.ESCALATE.value:
        renderer.error(
            f"Reasoning gate: ESCALATE — {gate['justification']}"
        )
        finish_run(root, audit_run.run_id, "escalated")
        return {
            "status": "escalated",
            "audit_run_id": audit_run.run_id,
            "reasoning_gate": gate,
            "tool_calls": 0,
            "turns": 0,
        }

    # Build prompt based on reasoning mode
    if gate_mode == ReasoningMode.LLM_SCOPED.value:
        system_prompt = build_scoped_prompt(
            root, active_cell_id, radius,
            gate["hot_edges"], task_description,
        )
    else:
        system_prompt = _build_system_prompt(
            registry, active_cell_id, radius,
        )

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": task_description},
    ]

    tool_call_count = 0
    status = "ok"

    try:
        for _turn in range(max_turns):
            # Call LLM via unified provider interface
            response = call_llm(
                provider, effective_key, effective_model,
                system_prompt, messages, tools,
                renderer=renderer,
            )

            assistant_content = response.raw.get("assistant_content", [])
            messages.append({"role": "assistant", "content": assistant_content})

            # If no tool calls, the model is done
            tool_use_blocks = response.tool_calls
            if not tool_use_blocks:
                break

            # Process tool calls
            tool_results: list[dict[str, Any]] = []
            for block in tool_use_blocks:
                tool_call_count += 1
                api_name = block["name"]
                arguments = block["input"]
                block_id = block["id"]

                try:
                    real_name = registry.resolve_api_name(api_name)
                except KeyError:
                    renderer.tool_result(api_name, {}, error=f"Unknown tool: {api_name}")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block_id,
                        "content": json.dumps({"error": f"Unknown tool: {api_name}"}),
                        "is_error": True,
                    })
                    continue

                renderer.tool_start(real_name, arguments)

                try:
                    result = registry.call(real_name, arguments)
                except Exception as exc:
                    error_msg = str(exc)
                    renderer.tool_result(real_name, {}, error=error_msg)
                    append_event(root, audit_run.run_id, "tool.error", {
                        "tool": real_name, "error": error_msg,
                    })
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block_id,
                        "content": json.dumps({"error": error_msg}),
                        "is_error": True,
                    })
                    continue

                # Handle approval flow
                if real_name == "port.check" and result.get("requires_approval"):
                    reasons = result.get("approval_reasons", ["Breaking change detected"])
                    approved = renderer.approval_prompt(reasons)
                    if approved:
                        task_id = arguments.get("task_id", "")
                        try:
                            registry.call("repo.approve_patch", {
                                "task_id": task_id,
                                "approver": "human:terminal",
                                "reason": "Approved via hx run interactive prompt",
                            })
                            result["human_approved"] = True
                        except Exception as exc:
                            renderer.error(f"Approval failed: {exc}")
                    else:
                        result["human_denied"] = True
                        renderer.error("Change denied by user")

                renderer.tool_result(real_name, result)
                append_event(root, audit_run.run_id, "tool.call", {
                    "tool": real_name,
                    "arguments": _safe_args(arguments),
                })

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block_id,
                    "content": json.dumps(
                        _compress_tool_result(real_name, result),
                        default=str,
                    ),
                })

            messages.append({"role": "user", "content": tool_results})

            # Feedback integrity: check holonomy on affected ports
            affected_ports = []
            for block in tool_use_blocks:
                name = block["name"].replace("_", ".")
                if name in ("port.check", "repo.commit_patch"):
                    args = block["input"] or {}
                    if args.get("task_id"):
                        try:
                            from hx.repo_ops import load_task
                            task = load_task(root, args["task_id"])
                            for p in task.port_check.get(
                                "impacted_ports", [],
                            ):
                                affected_ports.append(p.get("port_id"))
                        except Exception:
                            pass
            if affected_ports:
                integrity = check_feedback_integrity(
                    root, affected_ports,
                )
                if integrity:
                    append_event(
                        root, audit_run.run_id,
                        "feedback.integrity_warning",
                        {"warnings": integrity},
                    )

    except KeyboardInterrupt:
        status = "interrupted"
        renderer.error("Interrupted by user")
    except Exception as exc:
        status = "error"
        renderer.error(str(exc))

    finish_run(root, audit_run.run_id, status)
    renderer.session_end(status, tool_call_count)

    return {
        "status": status,
        "audit_run_id": audit_run.run_id,
        "tool_calls": tool_call_count,
        "turns": min(_turn + 1, max_turns) if "_turn" in dir() else 0,
    }


def _safe_args(arguments: dict) -> dict:
    """Redact large values for audit logging."""
    safe = {}
    for key, value in arguments.items():
        if isinstance(value, str) and len(value) > 500:
            safe[key] = f"<{len(value)} chars>"
        else:
            safe[key] = value
    return safe
