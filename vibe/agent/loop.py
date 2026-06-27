"""The agent loop — the heart of the whole thing.

    user message
        → send (messages + tool schemas) to the model
        → model replies with text and/or tool calls
        → execute each tool (with confirmation for write/edit/bash)
        → append results, loop
        → stop when the model replies with no tool calls

It also implements a text-protocol fallback: if the model emits no native tool
calls but its text contains a ```tool {...}``` block, we parse and run that. This
lets models without function-calling support still use the tools.
"""

from __future__ import annotations

import json
import re

from ..errors import ToolError
from ..llm.ollama import OllamaClient, ToolCall
from ..tools.base import ToolContext, ToolRegistry
from ..ui.render import UI
from .prompt import build_system_prompt

# Matches any ```fence ... ``` block (```tool, ```json, plain ```), capturing
# the body. Local models are inconsistent about the language tag, so we accept
# any fence and decide by the JSON shape inside.
_FENCE = re.compile(r"```[a-zA-Z0-9_]*[ \t]*\n(.*?)```", re.DOTALL)


def _as_tool_call(data: object) -> ToolCall | None:
    """Return a ToolCall if ``data`` looks like one, else None. Accepts the
    common key spellings local models emit (name/tool, arguments/args/params)."""
    if not isinstance(data, dict):
        return None
    name = data.get("name") or data.get("tool")
    args = data.get("arguments")
    if args is None:
        args = data.get("args") or data.get("parameters") or {}
    if not isinstance(name, str) or not name or not isinstance(args, dict):
        return None
    return ToolCall(name=name, arguments=args,
                    raw={"function": {"name": name, "arguments": args}})


def parse_text_tool_calls(content: str) -> list[ToolCall]:
    """Best-effort parse of text-protocol tool calls from assistant text.

    Scans every fenced code block (regardless of language tag) plus a bare
    top-level JSON object, and keeps the ones whose JSON has a tool name +
    arguments. This is what lets a model with no native tool-calling — or one
    that wraps its call in ```json instead of ```tool — still drive the tools.
    """
    candidates = [m.group(1).strip() for m in _FENCE.finditer(content)]
    stripped = content.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        candidates.append(stripped)

    calls: list[ToolCall] = []
    seen: set[tuple[str, str]] = set()
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        call = _as_tool_call(data)
        if call is None:
            continue
        key = (call.name, json.dumps(call.arguments, sort_keys=True))
        if key not in seen:
            seen.add(key)
            calls.append(call)
    return calls


class Agent:
    def __init__(self, client: OllamaClient, registry: ToolRegistry,
                 ctx: ToolContext, ui: UI):
        self.client = client
        self.registry = registry
        self.ctx = ctx
        self.ui = ui
        self.messages: list[dict] = [
            {"role": "system",
             "content": build_system_prompt(ctx, registry.names())}
        ]

    def reset(self) -> None:
        """Clear the conversation but keep the (rebuilt) system prompt."""
        self.messages = [
            {"role": "system",
             "content": build_system_prompt(self.ctx, self.registry.names())}
        ]

    def run_turn(self, user_input: str) -> None:
        self.messages.append({"role": "user", "content": user_input})

        for _ in range(self.ctx.config.max_iterations):
            result = self.client.chat(
                self.messages,
                tools=self.registry.schemas(),
                on_text=self.ui.stream_assistant,
            )
            self.ui.end_assistant()

            assistant_msg: dict = {"role": "assistant", "content": result.content}
            if result.raw_tool_calls:
                assistant_msg["tool_calls"] = result.raw_tool_calls
            self.messages.append(assistant_msg)

            tool_calls = result.tool_calls
            if not tool_calls:
                tool_calls = parse_text_tool_calls(result.content)
            if not tool_calls:
                return  # final answer — hand control back to the user

            for call in tool_calls:
                self._execute(call)

        self.ui.warn("Reached the max tool-iteration limit; stopping this turn.")

    # -- one tool call -----------------------------------------------------

    def _execute(self, call: ToolCall) -> None:
        tool = self.registry.get(call.name)
        if tool is None:
            self._record_result(call, f"Error: unknown tool '{call.name}'.")
            return

        self.ui.show_tool_call(call.name, call.arguments)
        try:
            if tool.requires_confirmation and not self.ctx.config.auto_approve:
                preview = tool.preview(call.arguments, self.ctx) if tool.preview else None
                if not self.ui.confirm(call.name, preview):
                    self._record_result(call, "User declined this action.")
                    return
            output = tool.handler(call.arguments, self.ctx)
        except ToolError as e:
            self.ui.show_tool_result(call.name, f"Error: {e}", is_error=True)
            self._record_result(call, f"Error: {e}")
            return
        except KeyError as e:
            msg = f"Error: missing required argument {e}"
            self.ui.show_tool_result(call.name, msg, is_error=True)
            self._record_result(call, msg)
            return

        self.ui.show_tool_result(call.name, output)
        self._record_result(call, output)

    def _record_result(self, call: ToolCall, content: str) -> None:
        self.messages.append(
            {"role": "tool", "tool_name": call.name, "content": content}
        )
