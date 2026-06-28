"""Unit tests for the tools and safety layer — run without Ollama.

    pytest
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vibe.agent.loop import Agent, parse_text_tool_calls
from vibe.config import Config
from vibe.errors import ToolError
from vibe.llm.ollama import ChatResult, ToolCall
from vibe.safety import resolve_in_root
from vibe.tools.base import ToolContext, build_default_registry
from vibe.trace import JsonlSink, Tracer, build_tracer
from vibe.ui.render import UI


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    config = Config(project_root=tmp_path)
    return ToolContext(project_root=tmp_path, config=config)


@pytest.fixture
def registry(ctx):
    return build_default_registry(ctx)


def call(registry, name, ctx, **args):
    return registry.get(name).handler(args, ctx)


# -- safety ---------------------------------------------------------------

def test_resolve_in_root_allows_inside(tmp_path):
    assert resolve_in_root("a/b.py", tmp_path) == (tmp_path / "a/b.py").resolve()


def test_resolve_in_root_blocks_escape(tmp_path):
    with pytest.raises(ToolError):
        resolve_in_root("../../etc/passwd", tmp_path)


# -- read / list ----------------------------------------------------------

def test_read_file(registry, ctx, tmp_path):
    (tmp_path / "hello.txt").write_text("line1\nline2\n")
    assert call(registry, "read_file", ctx, path="hello.txt") == "line1\nline2\n"


def test_read_missing_file(registry, ctx):
    with pytest.raises(ToolError):
        call(registry, "read_file", ctx, path="nope.txt")


def test_list_dir(registry, ctx, tmp_path):
    (tmp_path / "a.py").write_text("x")
    (tmp_path / "sub").mkdir()
    out = call(registry, "list_dir", ctx, path=".")
    assert "a.py" in out and "sub/" in out


# -- write ----------------------------------------------------------------

def test_write_new_file(registry, ctx, tmp_path):
    call(registry, "write_file", ctx, path="new.py", content="print(1)\n")
    assert (tmp_path / "new.py").read_text() == "print(1)\n"


def test_write_refuses_existing(registry, ctx, tmp_path):
    (tmp_path / "exists.py").write_text("old")
    with pytest.raises(ToolError):
        call(registry, "write_file", ctx, path="exists.py", content="new")


# -- edit (the reliability crux) ------------------------------------------

def test_edit_success(registry, ctx, tmp_path):
    (tmp_path / "f.py").write_text("def foo():\n    return 1\n")
    call(registry, "edit_file", ctx, path="f.py",
         old_string="return 1", new_string="return 2")
    assert (tmp_path / "f.py").read_text() == "def foo():\n    return 2\n"


def test_edit_not_found(registry, ctx, tmp_path):
    (tmp_path / "f.py").write_text("a = 1\n")
    with pytest.raises(ToolError, match="not found"):
        call(registry, "edit_file", ctx, path="f.py",
             old_string="b = 2", new_string="b = 3")


def test_edit_not_unique(registry, ctx, tmp_path):
    (tmp_path / "f.py").write_text("x\nx\n")
    with pytest.raises(ToolError, match="unique"):
        call(registry, "edit_file", ctx, path="f.py",
             old_string="x", new_string="y")


def test_edit_preview_returns_diff(registry, ctx, tmp_path):
    (tmp_path / "f.py").write_text("a = 1\n")
    tool = registry.get("edit_file")
    diff = tool.preview({"path": "f.py", "old_string": "a = 1", "new_string": "a = 2"}, ctx)
    assert "-a = 1" in diff and "+a = 2" in diff


def test_edit_noop_identical(registry, ctx, tmp_path):
    (tmp_path / "f.py").write_text("a = 1\n")
    with pytest.raises(ToolError, match="identical"):
        call(registry, "edit_file", ctx, path="f.py",
             old_string="a = 1", new_string="a = 1")


def test_edit_missing_target(registry, ctx, tmp_path):
    (tmp_path / "f.py").write_text("a = 1\n")
    with pytest.raises(ToolError, match="empty"):
        call(registry, "edit_file", ctx, path="f.py")


# -- edit: whitespace-tolerant (fuzzy) matching ---------------------------

def test_edit_fuzzy_trailing_whitespace(registry, ctx, tmp_path):
    # No exact match (model added trailing spaces), but the line matches once.
    (tmp_path / "f.py").write_text("x = 1\ny = 2\n")
    call(registry, "edit_file", ctx, path="f.py",
         old_string="x = 1   ", new_string="x = 11")
    assert (tmp_path / "f.py").read_text() == "x = 11\ny = 2\n"


def test_edit_fuzzy_indentation_multiline(registry, ctx, tmp_path):
    # Model under-indents a two-line block; stripped lines still match uniquely.
    (tmp_path / "f.py").write_text("def f():\n    a = 1\n    b = 2\n")
    call(registry, "edit_file", ctx, path="f.py",
         old_string="  a = 1\n  b = 2", new_string="  a = 10\n  b = 20")
    assert (tmp_path / "f.py").read_text() == "def f():\n  a = 10\n  b = 20\n"


def test_edit_fuzzy_ambiguous_refuses(registry, ctx, tmp_path):
    # Two whitespace-equal candidates: refuse rather than guess a location.
    (tmp_path / "f.py").write_text("a = 1\na = 1\n")
    with pytest.raises(ToolError, match="not found"):
        call(registry, "edit_file", ctx, path="f.py",
             old_string="a = 1 ", new_string="a = 2")


def test_edit_did_you_mean_hint(registry, ctx, tmp_path):
    # A near-miss should point the model at the closest real line.
    (tmp_path / "f.py").write_text("def go():\n    result = compute(x)\n")
    with pytest.raises(ToolError, match="Closest line"):
        call(registry, "edit_file", ctx, path="f.py",
             old_string="result = kompute(x)", new_string="result = compute(y)")


# -- edit: batched multi-edit ---------------------------------------------

def test_edit_batch(registry, ctx, tmp_path):
    (tmp_path / "f.py").write_text("a = 1\nb = 2\n")
    call(registry, "edit_file", ctx, path="f.py",
         edits=[{"old_string": "a = 1", "new_string": "a = 10"},
                {"old_string": "b = 2", "new_string": "b = 20"}])
    assert (tmp_path / "f.py").read_text() == "a = 10\nb = 20\n"


def test_edit_batch_applies_in_order(registry, ctx, tmp_path):
    # The second edit targets text the first one produced.
    (tmp_path / "f.py").write_text("value = 1\n")
    call(registry, "edit_file", ctx, path="f.py",
         edits=[{"old_string": "value = 1", "new_string": "value = 2"},
                {"old_string": "value = 2", "new_string": "value = 3"}])
    assert (tmp_path / "f.py").read_text() == "value = 3\n"


def test_edit_batch_result_counts(registry, ctx, tmp_path):
    (tmp_path / "f.py").write_text("a = 1\nb = 2\n")
    out = call(registry, "edit_file", ctx, path="f.py",
               edits=[{"old_string": "a = 1", "new_string": "a = 9"},
                      {"old_string": "b = 2", "new_string": "b = 9"}])
    assert "2 edits" in out


def test_edit_batch_one_failure_aborts(registry, ctx, tmp_path):
    # If any edit can't apply, the file is left untouched.
    (tmp_path / "f.py").write_text("a = 1\nb = 2\n")
    with pytest.raises(ToolError):
        call(registry, "edit_file", ctx, path="f.py",
             edits=[{"old_string": "a = 1", "new_string": "a = 9"},
                    {"old_string": "nope", "new_string": "x"}])
    assert (tmp_path / "f.py").read_text() == "a = 1\nb = 2\n"


def test_edit_batch_preview(registry, ctx, tmp_path):
    (tmp_path / "f.py").write_text("a = 1\nb = 2\n")
    tool = registry.get("edit_file")
    diff = tool.preview({"path": "f.py",
                         "edits": [{"old_string": "a = 1", "new_string": "a = 9"},
                                   {"old_string": "b = 2", "new_string": "b = 9"}]}, ctx)
    assert "+a = 9" in diff and "+b = 9" in diff


def test_edit_empty_edits_list(registry, ctx, tmp_path):
    (tmp_path / "f.py").write_text("a = 1\n")
    with pytest.raises(ToolError, match="empty"):
        call(registry, "edit_file", ctx, path="f.py", edits=[])


def test_edit_edits_wrong_type(registry, ctx, tmp_path):
    (tmp_path / "f.py").write_text("a = 1\n")
    with pytest.raises(ToolError, match="list"):
        call(registry, "edit_file", ctx, path="f.py", edits="a = 1")


# -- grep -----------------------------------------------------------------

def test_grep_finds_match(registry, ctx, tmp_path):
    (tmp_path / "f.py").write_text("hello world\nfoo bar\n")
    out = call(registry, "grep", ctx, pattern="foo")
    assert "foo bar" in out


def test_grep_no_match(registry, ctx, tmp_path):
    (tmp_path / "f.py").write_text("nothing here\n")
    assert "No matches" in call(registry, "grep", ctx, pattern="zzz")


# -- bash -----------------------------------------------------------------

def test_run_bash(registry, ctx):
    out = call(registry, "run_bash", ctx, command="echo hi")
    assert "hi" in out and "exit code 0" in out


# -- text-protocol fallback parser ----------------------------------------

def test_parse_text_tool_calls():
    content = 'sure\n```tool\n{"name": "read_file", "arguments": {"path": "x"}}\n```'
    calls = parse_text_tool_calls(content)
    assert len(calls) == 1
    assert calls[0].name == "read_file"
    assert calls[0].arguments == {"path": "x"}


def test_parse_text_tool_calls_ignores_bad_json():
    assert parse_text_tool_calls("```tool\nnot json\n```") == []


def test_parse_text_tool_calls_accepts_json_fence():
    # Real qwen behaviour: wraps the call in a ```json fence, not ```tool.
    content = 'Here you go:\n```json\n{"name": "write_file", "arguments": {"path": "a.py", "content": "x"}}\n```'
    calls = parse_text_tool_calls(content)
    assert len(calls) == 1 and calls[0].name == "write_file"


def test_parse_text_tool_calls_ignores_non_tool_blocks():
    # An example ```bash block alongside the real call must not break parsing.
    content = '```bash\npython3 x.py\n```\n```json\n{"name": "list_dir", "arguments": {}}\n```'
    calls = parse_text_tool_calls(content)
    assert len(calls) == 1 and calls[0].name == "list_dir"


def test_parse_text_tool_calls_bare_json():
    calls = parse_text_tool_calls('{"name": "grep", "arguments": {"pattern": "x"}}')
    assert len(calls) == 1 and calls[0].name == "grep"


# -- reasoning trace ------------------------------------------------------

class StubClient:
    """A fake OllamaClient that replays scripted ChatResults — no Ollama."""

    def __init__(self, scripted: list[ChatResult], model: str = "stub") -> None:
        self.model = model
        self._scripted = list(scripted)

    def chat(self, messages, tools=None, on_text=None):
        return self._scripted.pop(0)


def _read_only_call(name, args):
    return ToolCall(name, args, {"function": {"name": name, "arguments": args}})


def _drive(tmp_path, scripted, trace_file, auto=True):
    config = Config(project_root=tmp_path, auto_approve=auto)
    ctx = ToolContext(project_root=tmp_path, config=config)
    registry = build_default_registry(ctx)
    tracer = Tracer([JsonlSink(trace_file)])
    agent = Agent(StubClient(scripted), registry, ctx, UI(), tracer=tracer)
    agent.run_turn("what is in f.py?")
    tracer.close()
    return [json.loads(line) for line in trace_file.read_text().splitlines()]


def test_trace_records_reasoning_trajectory(tmp_path):
    (tmp_path / "f.py").write_text("a = 1\n")
    scripted = [
        ChatResult(
            content="I'll read f.py first.",
            tool_calls=[_read_only_call("read_file", {"path": "f.py"})],
            raw_tool_calls=[{"function": {"name": "read_file",
                                          "arguments": {"path": "f.py"}}}],
            stats={"prompt_eval_count": 100, "eval_count": 12,
                   "total_duration": 1_500_000_000},
        ),
        ChatResult(content="The file holds a = 1.", stats={"eval_count": 8}),
    ]
    records = _drive(tmp_path, scripted, tmp_path / "trace.jsonl")
    kinds = [r["kind"] for r in records]

    # the full intent -> action -> observation trajectory is present
    assert kinds.count("llm_request") == 2
    assert {"llm_response", "interpretation", "observation"} <= set(kinds)
    assert kinds[-1] == "turn_end"

    resp = next(r for r in records if r["kind"] == "llm_response")
    assert resp["reasoning"] == "I'll read f.py first."
    assert resp["prompt_tokens"] == 100 and resp["gen_tokens"] == 12
    assert resp["seconds"] == 1.5

    interp = next(r for r in records if r["kind"] == "interpretation")
    assert interp["source"] == "native"
    assert interp["calls"][0]["tool"] == "read_file"

    obs = next(r for r in records if r["kind"] == "observation")
    assert obs["tool"] == "read_file" and obs["is_error"] is False
    assert obs["chars"] > 0

    assert "final answer" in records[-1]["reason"]


def test_trace_marks_text_parsed_source(tmp_path):
    scripted = [
        ChatResult(content='```json\n{"name": "list_dir", "arguments": {}}\n```'),
        ChatResult(content="done"),
    ]
    records = _drive(tmp_path, scripted, tmp_path / "trace.jsonl")
    interp = next(r for r in records if r["kind"] == "interpretation")
    assert interp["source"] == "text-parsed"
    assert interp["calls"][0]["tool"] == "list_dir"


def test_trace_records_tool_error(tmp_path):
    # editing a missing file should be observed as an error, not crash the trace
    scripted = [
        ChatResult(
            content="editing",
            tool_calls=[_read_only_call("edit_file",
                                        {"path": "nope.py", "old_string": "a",
                                         "new_string": "b"})],
            raw_tool_calls=[{"function": {"name": "edit_file", "arguments": {}}}],
        ),
        ChatResult(content="could not edit"),
    ]
    records = _drive(tmp_path, scripted, tmp_path / "trace.jsonl")
    obs = next(r for r in records if r["kind"] == "observation")
    assert obs["is_error"] is True


def test_tracer_without_sinks_is_noop():
    calls = []
    Tracer().emit("llm_request", 0, model="x")  # must not raise
    assert calls == []


def test_console_sink_renders_all_kinds(capsys):
    tracer = build_tracer(verbosity=2)
    tracer.emit("llm_request", 0, model="m", messages=2, tools=6,
                sent=[{"role": "user", "content": "hi [not markup]"}])
    tracer.emit("llm_response", 0, reasoning="thinking", tool_calls=1,
                raw_tool_calls=[{"x": 1}], prompt_tokens=5, gen_tokens=3, seconds=0.2)
    tracer.emit("interpretation", 0, source="native",
                calls=[{"tool": "read_file", "args": {"path": "x"}}])
    tracer.emit("observation", 0, tool="read_file", chars=10, is_error=False,
                result="data")
    tracer.emit("turn_end", 0, reason="final answer")
    err = capsys.readouterr().err
    assert "POST /api/chat" in err
    assert "reasoning" in err and "thinking" in err
    assert "read_file" in err and "final answer" in err
