"""Agent loop: orchestrates an LLM with hx governance tools."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hx.audit import append_event, finish_run, start_run
from hx.authz import allowed_cells as calc_allowed_cells
from hx.config import ensure_hx_dirs
from hx.hexmap import load_hexmap
from hx.memory import load_memory_context
from hx.stream import StreamRenderer
from hx.tools import ToolRegistry


def _memory_section(root: Path) -> str:
    """Build an optional memory context section for the system prompt."""
    memory_block = load_memory_context(root)
    if not memory_block:
        return ""
    return f"""
## Memory Context
{memory_block}
"""


def _build_system_prompt(
    registry: ToolRegistry,
    active_cell_id: str,
    radius: int,
) -> str:
    base = registry.root
    hexmap = load_hexmap(base)
    cell = hexmap.cell(active_cell_id)
    allowed = calc_allowed_cells(hexmap, active_cell_id, radius)

    port_summaries = []
    for cid in allowed:
        for i in range(6):
            port_info = registry.call("port.describe", {"cell_id": cid, "side_index": i})
            if port_info.get("neighbor_cell_id"):
                neighbor = port_info["neighbor_cell_id"]
                direction = port_info.get("direction", "none")
                port_summaries.append(
                    f"  {cid}[{i}] → {neighbor} ({direction})"
                )

    ports_text = "\n".join(port_summaries[:12]) if port_summaries else "  (no active ports)"

    return f"""You are an AI coding agent operating inside hx governance.

## Your Cell
- Active cell: {active_cell_id}
- Radius: R{radius}
- Summary: {cell.summary}
- Invariants: {', '.join(cell.invariants) or 'none'}
- Allowed cells: {', '.join(allowed)}

## Active Ports
{ports_text}

## Governance Rules
- You may ONLY read/write files within your allowed cells.
- Use repo.read to read files and repo.search to search code.
- Use repo.stage_patch to propose changes as unified diffs.
- After staging, run port.check to detect boundary impacts.
- If port.check indicates requires_approval, the user will be prompted.
- Run proof.collect and proof.verify before committing.
- Run tests.run to validate changes.
- Use repo.commit_patch to finalize.
- Use cmd.run for shell commands (must be in the policy allowlist).

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
    model: str = "claude-sonnet-4-20250514",
    max_turns: int = 50,
    color: bool = False,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Run the governed agent loop. Returns a summary dict."""
    try:
        import anthropic
    except ImportError:
        return {
            "status": "error",
            "error": "anthropic package not installed. Run: pip install anthropic",
        }

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

    client = anthropic.Anthropic(api_key=api_key)
    tools = registry.anthropic_tool_schemas()
    system_prompt = _build_system_prompt(registry, active_cell_id, radius)

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": task_description},
    ]

    tool_call_count = 0
    status = "ok"

    try:
        for _turn in range(max_turns):
            # Call Claude with streaming
            with client.messages.stream(
                model=model,
                max_tokens=8192,
                system=system_prompt,
                messages=messages,
                tools=tools,
            ) as stream:
                assistant_content: list[dict[str, Any]] = []
                current_text = ""
                tool_use_blocks: list[dict[str, Any]] = []

                for event in stream:
                    if event.type == "content_block_start":
                        if event.content_block.type == "text":
                            current_text = ""
                        elif event.content_block.type == "tool_use":
                            tool_use_blocks.append({
                                "id": event.content_block.id,
                                "name": event.content_block.name,
                                "input": {},
                            })
                    elif event.type == "content_block_delta":
                        if event.delta.type == "text_delta":
                            renderer.text_delta(event.delta.text)
                            current_text += event.delta.text
                        elif event.delta.type == "input_json_delta":
                            pass  # accumulated in final message
                    elif event.type == "content_block_stop":
                        if current_text:
                            assistant_content.append({
                                "type": "text",
                                "text": current_text,
                            })
                            current_text = ""

                renderer.text_done()

                # Get the final message to extract complete tool_use blocks
                final_message = stream.get_final_message()
                tool_use_blocks = [
                    block for block in final_message.content
                    if block.type == "tool_use"
                ]

                # Build assistant content from final message
                assistant_content = []
                for block in final_message.content:
                    if block.type == "text":
                        assistant_content.append({"type": "text", "text": block.text})
                    elif block.type == "tool_use":
                        assistant_content.append({
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": block.input,
                        })

                messages.append({"role": "assistant", "content": assistant_content})

                # If no tool use, the model is done
                if not tool_use_blocks:
                    break

                # Process tool calls
                tool_results: list[dict[str, Any]] = []
                for block in tool_use_blocks:
                    tool_call_count += 1
                    api_name = block.name
                    arguments = block.input

                    try:
                        real_name = registry.resolve_api_name(api_name)
                    except KeyError:
                        renderer.tool_result(api_name, {}, error=f"Unknown tool: {api_name}")
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps({"error": f"Unknown tool: {api_name}"}),
                            "is_error": True,
                        })
                        continue

                    renderer.tool_start(real_name, arguments)

                    # Intercept port.check for approval flow
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
                            "tool_use_id": block.id,
                            "content": json.dumps({"error": error_msg}),
                            "is_error": True,
                        })
                        continue

                    # Handle approval flow
                    if real_name == "port.check" and result.get("requires_approval"):
                        reasons = result.get("approval_reasons", ["Breaking change detected"])
                        approved = renderer.approval_prompt(reasons)
                        if approved:
                            # Find task_id from arguments and auto-approve
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
                        "tool_use_id": block.id,
                        "content": json.dumps(result, default=str),
                    })

                messages.append({"role": "user", "content": tool_results})

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
