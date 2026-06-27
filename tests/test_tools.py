"""Unit tests for the tools and safety layer — run without Ollama.

    pytest
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vibe.agent.loop import parse_text_tool_calls
from vibe.config import Config
from vibe.errors import ToolError
from vibe.safety import resolve_in_root
from vibe.tools.base import ToolContext, build_default_registry


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
