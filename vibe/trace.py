"""Structured reasoning trace for the agent loop.

The agent emits a small set of events at each decision point; sinks render them.
The console view (``-v``/``-vv``) and the JSONL file (``--trace``) are two
renderings of the *same* event stream, so they can never disagree.

These models have no hidden chain-of-thought: their "reasoning" is just the text
they emit, the trajectory of tool calls they choose, and how each tool result
shapes the next step. So the trace records exactly that — the
intent -> action -> observation triple — with the message transcript as the
source of truth. Treat the prose as a hint; the actions and their results are
the reliable signal.

Event kinds:
  llm_request    — about to call the model (model, context size, tools offered)
  llm_response   — the model's reply: reasoning text, tool calls, token/timing
  interpretation — how the reply became actions (native vs text-parsed, calls)
  observation    — a tool result fed back into the conversation
  turn_end       — why the turn stopped (final answer / max iterations)
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.text import Text


@dataclass
class Event:
    kind: str
    iteration: int
    data: dict[str, Any]
    ts: float = field(default_factory=time.time)


class Tracer:
    """Fans events out to sinks. A tracer with no sinks is a cheap no-op."""

    def __init__(self, sinks: list | None = None) -> None:
        self.sinks: list = sinks or []

    def emit(self, kind: str, iteration: int, **data: Any) -> None:
        if not self.sinks:
            return
        event = Event(kind, iteration, data)
        for sink in self.sinks:
            sink.handle(event)

    def set_console_level(self, level: int) -> None:
        """Add/replace/remove the live console sink (used by /verbose)."""
        self.sinks = [s for s in self.sinks if not isinstance(s, ConsoleSink)]
        if level > 0:
            self.sinks.append(ConsoleSink(Console(stderr=True), min(level, 2)))

    def close(self) -> None:
        for sink in self.sinks:
            close = getattr(sink, "close", None)
            if close:
                close()


# --------------------------------------------------------------------------
# sinks
# --------------------------------------------------------------------------
class JsonlSink:
    """Appends one JSON object per event — replayable, greppable, diffable."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._fh = path.open("a", encoding="utf-8")

    def handle(self, event: Event) -> None:
        record = {
            "ts": round(event.ts, 3),
            "kind": event.kind,
            "iteration": event.iteration,
            **event.data,
        }
        self._fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit] + "…"


class ConsoleSink:
    """Renders events as a live, human-readable trace (to stderr by default).

    level 1 = the readable intent->action->observation trace;
    level 2 = also the full payloads (messages sent, raw reply, full results).
    """

    SUMMARY = 240

    def __init__(self, console: Console, level: int = 1) -> None:
        self.console = console
        self.level = level

    def handle(self, event: Event) -> None:
        getattr(self, f"_{event.kind}", self._default)(event)

    def _line(self, *parts: tuple[str, str | None]) -> None:
        text = Text()
        for chunk, style in parts:
            text.append(chunk, style=style)
        self.console.print(text)

    def _llm_request(self, e: Event) -> None:
        d = e.data
        self._line(
            ("→ POST /api/chat  ", "dim"),
            (f"model={d.get('model')}  msgs={d.get('messages')}  "
             f"tools={d.get('tools')}", "dim"),
        )
        if self.level >= 2:
            # The JSONL sink keeps the full context; on the console show only the
            # tail (what newly drove this call) to stay readable.
            for m in (d.get("sent") or [])[-3:]:
                self._line(
                    (f"    {m.get('role')}: ", "dim"),
                    (_clip(m.get("content", ""), 2000), "dim"),
                )

    def _llm_response(self, e: Event) -> None:
        d = e.data
        bits = []
        if d.get("prompt_tokens") is not None:
            bits.append(f"prompt={d['prompt_tokens']} tok")
        if d.get("gen_tokens") is not None:
            bits.append(f"gen={d['gen_tokens']} tok")
        if d.get("seconds") is not None:
            bits.append(f"{d['seconds']}s")
        self._line(("← reply  ", "dim"), ("  ".join(bits), "dim"))
        text = d.get("reasoning") or ""
        if text.strip():
            limit = 4000 if self.level >= 2 else self.SUMMARY
            self._line(("  reasoning: ", "cyan"), (_clip(text, limit), None))
        if self.level >= 2 and d.get("raw_tool_calls"):
            self._line(("    raw_tool_calls: ", "dim"),
                       (_clip(json.dumps(d["raw_tool_calls"]), 2000), "dim"))

    def _interpretation(self, e: Event) -> None:
        d = e.data
        src = d.get("source")
        for c in d.get("calls") or []:
            self._line(
                ("  → ", "green"),
                (str(c.get("tool")), "green bold"),
                (f"({_clip(json.dumps(c.get('args', {})), 200)})", "dim"),
                (f"  ({src})", "dim"),
            )

    def _observation(self, e: Event) -> None:
        d = e.data
        mark, style = ("✗", "red") if d.get("is_error") else ("✓", "green")
        parts: list[tuple[str, str | None]] = [
            ("  ", None), (mark, style),
            (f" {d.get('tool')} → {d.get('chars')} chars fed back", "dim"),
        ]
        if self.level >= 2:
            parts.append((f"  {_clip(d.get('result', ''), 4000)}", "dim"))
        self._line(*parts)

    def _turn_end(self, e: Event) -> None:
        self._line(("decision: ", "dim"), (str(e.data.get("reason")), "dim"))

    def _default(self, e: Event) -> None:
        self._line((f"{e.kind}: ", "dim"), (_clip(json.dumps(e.data, default=str), 240), "dim"))


# --------------------------------------------------------------------------
# construction helpers
# --------------------------------------------------------------------------
def default_trace_path() -> Path:
    ts = time.strftime("%Y%m%d-%H%M%S")
    return Path.home() / ".vibe" / "traces" / f"session-{ts}.jsonl"


def build_tracer(verbosity: int = 0, trace_file: Path | None = None) -> Tracer:
    """Build a tracer from CLI options. Both sinks are optional and independent."""
    sinks: list = []
    if verbosity > 0:
        sinks.append(ConsoleSink(Console(stderr=True), min(verbosity, 2)))
    if trace_file is not None:
        sinks.append(JsonlSink(trace_file))
    return Tracer(sinks)
