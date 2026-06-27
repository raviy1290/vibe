"""A thin, transparent client over Ollama's HTTP API.

We talk to ``POST /api/chat`` directly with httpx (rather than the `ollama`
python package) so the request/response shape is visible — this is the whole
point of "understand every part".

Streaming response shape (one JSON object per line / NDJSON):

    {"message": {"role": "assistant", "content": "tok"}, "done": false}
    {"message": {"role": "assistant", "content": "",  "tool_calls": [...]}, ...}
    {"message": {"role": "assistant", "content": ""}, "done": true, ...}

Tool calls come back as:

    "tool_calls": [{"function": {"name": "read_file", "arguments": {"path": "x"}}}]

Note Ollama gives ``arguments`` as a real object, not a JSON string.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable, Iterable

import httpx

from ..errors import LLMError

# Type of the per-token streaming callback.
TextCallback = Callable[[str], None]


@dataclass
class ToolCall:
    name: str
    arguments: dict
    raw: dict  # exactly as Ollama returned it, so we can echo it back verbatim


@dataclass
class ChatResult:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw_tool_calls: list[dict] = field(default_factory=list)


def _normalize_arguments(args) -> dict:
    """Ollama usually returns a dict; some models/versions return a JSON string."""
    if isinstance(args, dict):
        return args
    if isinstance(args, str):
        try:
            parsed = json.loads(args)
            return parsed if isinstance(parsed, dict) else {"value": parsed}
        except json.JSONDecodeError:
            return {}
    return {}


class OllamaClient:
    def __init__(self, host: str, model: str, temperature: float = 0.2,
                 timeout: float = 600.0):
        self.host = host.rstrip("/")
        self.model = model
        self.temperature = temperature
        self._client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._client.close()

    # -- discovery ---------------------------------------------------------

    def list_models(self) -> list[str]:
        try:
            r = self._client.get(f"{self.host}/api/tags")
            r.raise_for_status()
            return [m["name"] for m in r.json().get("models", [])]
        except (httpx.HTTPError, KeyError) as e:
            raise LLMError(f"Could not list models from {self.host}: {e}") from e

    # -- the one call that matters ----------------------------------------

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        on_text: TextCallback | None = None,
    ) -> ChatResult:
        """Send the conversation, stream assistant text via ``on_text``, and
        return the assembled assistant turn (text + any tool calls)."""
        body = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "options": {"temperature": self.temperature},
        }
        if tools:
            body["tools"] = tools

        result = ChatResult()
        try:
            with self._client.stream("POST", f"{self.host}/api/chat", json=body) as resp:
                if resp.status_code != 200:
                    detail = resp.read().decode("utf-8", "replace")
                    raise LLMError(f"Ollama returned {resp.status_code}: {detail}")
                for line in resp.iter_lines():
                    self._consume_line(line, result, on_text)
        except httpx.ConnectError as e:
            raise LLMError(
                f"Could not reach Ollama at {self.host}. Is it running? "
                f"(try: `ollama serve`)  [{e}]"
            ) from e
        except httpx.HTTPError as e:
            raise LLMError(f"HTTP error talking to Ollama: {e}") from e

        return result

    def _consume_line(self, line: str, result: ChatResult,
                      on_text: TextCallback | None) -> None:
        if not line.strip():
            return
        try:
            chunk = json.loads(line)
        except json.JSONDecodeError:
            return  # ignore keep-alive / malformed fragments

        if "error" in chunk:
            raise LLMError(chunk["error"])

        msg = chunk.get("message") or {}
        text = msg.get("content") or ""
        if text:
            result.content += text
            if on_text:
                on_text(text)

        for raw_call in msg.get("tool_calls") or []:
            fn = raw_call.get("function", {})
            result.raw_tool_calls.append(raw_call)
            result.tool_calls.append(
                ToolCall(
                    name=fn.get("name", ""),
                    arguments=_normalize_arguments(fn.get("arguments", {})),
                    raw=raw_call,
                )
            )
