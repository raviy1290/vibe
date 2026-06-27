"""File tools: read_file, list_dir, write_file, edit_file.

The important one is ``edit_file``: it does an *exact-string* replacement and
fails loudly unless the target text appears exactly once. This is far more
reliable for small local models than asking them to regenerate whole files.
"""

from __future__ import annotations

import difflib
from pathlib import Path

from ..errors import ToolError
from ..safety import resolve_in_root
from .base import Tool, ToolContext

MAX_READ_CHARS = 60_000
SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules", ".mypy_cache"}


# --------------------------------------------------------------------------
# read_file
# --------------------------------------------------------------------------
def _read_file(args: dict, ctx: ToolContext) -> str:
    path = resolve_in_root(args["path"], ctx.project_root)
    if not path.exists():
        raise ToolError(f"File not found: {args['path']}")
    if path.is_dir():
        raise ToolError(f"{args['path']} is a directory; use list_dir.")
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        raise ToolError(f"Could not read {args['path']}: {e}") from e

    lines = text.splitlines()
    offset = int(args.get("offset", 0) or 0)
    limit = args.get("limit")
    if offset or limit is not None:
        end = offset + int(limit) if limit is not None else len(lines)
        lines = lines[offset:end]
        text = "\n".join(lines)

    if len(text) > MAX_READ_CHARS:
        text = text[:MAX_READ_CHARS] + "\n... [truncated; use offset/limit to read more]"
    return text or "[file is empty]"


# --------------------------------------------------------------------------
# list_dir
# --------------------------------------------------------------------------
def _list_dir(args: dict, ctx: ToolContext) -> str:
    path = resolve_in_root(args.get("path", "."), ctx.project_root)
    if not path.exists():
        raise ToolError(f"Directory not found: {args.get('path', '.')}")
    if not path.is_dir():
        raise ToolError(f"{args.get('path', '.')} is not a directory.")
    entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    out = []
    for entry in entries:
        if entry.name in SKIP_DIRS:
            continue
        out.append(entry.name + ("/" if entry.is_dir() else ""))
    rel = path.relative_to(ctx.project_root.resolve()) if path != ctx.project_root.resolve() else Path(".")
    return f"{rel}/\n" + ("\n".join(out) if out else "[empty]")


# --------------------------------------------------------------------------
# write_file  (new files only — existing files must go through edit_file)
# --------------------------------------------------------------------------
def _write_preview(args: dict, ctx: ToolContext) -> str:
    content = args.get("content", "")
    head = "\n".join(content.splitlines()[:40])
    more = "" if content.count("\n") < 40 else "\n... [more]"
    return f"Create new file: {args['path']}\n\n{head}{more}"


def _write_file(args: dict, ctx: ToolContext) -> str:
    path = resolve_in_root(args["path"], ctx.project_root)
    if path.exists():
        raise ToolError(
            f"{args['path']} already exists. Use edit_file to change an existing file."
        )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(args.get("content", ""), encoding="utf-8")
    except OSError as e:
        raise ToolError(f"Could not write {args['path']}: {e}") from e
    n = args.get("content", "").count("\n") + 1
    return f"Created {args['path']} ({n} lines)."


# --------------------------------------------------------------------------
# edit_file  (forgiving exact-string replace, single or batched)
# --------------------------------------------------------------------------
def _coerce_edits(args: dict) -> list[tuple[str, str]]:
    """Accept either the single old_string/new_string form or an ``edits`` list
    of {old_string, new_string} objects, and return a normalized [(old, new)]."""
    raw = args.get("edits")
    if raw is not None:
        if not isinstance(raw, list):
            raise ToolError("edits must be a list of {old_string, new_string} objects.")
        out: list[tuple[str, str]] = []
        for e in raw:
            if not isinstance(e, dict):
                raise ToolError("each item in edits must be an object with "
                                "old_string and new_string.")
            out.append((e.get("old_string", ""), e.get("new_string", "")))
        if not out:
            raise ToolError("edits is empty; provide at least one edit.")
        return out
    return [(args.get("old_string", ""), args.get("new_string", ""))]


def _fuzzy_apply(content: str, old: str, new: str) -> str | None:
    """Whitespace-tolerant fallback when ``old`` isn't an exact substring.

    Small models reliably copy *what* to change but often get indentation or
    trailing whitespace slightly wrong. We match ``old`` against ``content`` a
    line-block at a time, comparing each line stripped of surrounding
    whitespace. We only act on a single unambiguous match, and the diff +
    confirmation prompt remain the user's safety net.
    """
    src = content.splitlines(keepends=True)
    tgt = old.splitlines()
    n = len(tgt)
    if n == 0:
        return None
    norm_tgt = [t.strip() for t in tgt]
    hits = [
        i for i in range(len(src) - n + 1)
        if [s.strip() for s in src[i:i + n]] == norm_tgt
    ]
    if len(hits) != 1:
        return None
    i = hits[0]
    ends_nl = src[i + n - 1].endswith("\n")
    replacement = new + "\n" if ends_nl and not new.endswith("\n") else new
    return "".join(src[:i]) + replacement + "".join(src[i + n:])


def _no_match_message(content: str, old: str) -> str:
    """A guided error: point the model at the closest line so it can retry in
    one step instead of looping blindly."""
    needle = next((ln for ln in old.splitlines() if ln.strip()), old).strip()
    haystack = [ln for ln in content.splitlines() if ln.strip()]
    close = difflib.get_close_matches(needle, haystack, n=1, cutoff=0.6)
    hint = f"\nClosest line in the file is:\n    {close[0].strip()}" if close else ""
    return (
        "old_string was not found, even ignoring whitespace. Read the file "
        "again and copy the exact text you want to replace." + hint
    )


def _apply_one_edit(content: str, old: str, new: str) -> str:
    if old == "":
        raise ToolError("old_string must not be empty.")
    if old == new:
        raise ToolError("old_string and new_string are identical; nothing to change.")
    count = content.count(old)
    if count == 1:
        return content.replace(old, new, 1)
    if count > 1:
        raise ToolError(
            f"old_string appears {count} times; it must be unique. Include more "
            "surrounding context so it matches exactly one location."
        )
    spliced = _fuzzy_apply(content, old, new)
    if spliced is not None:
        return spliced
    raise ToolError(_no_match_message(content, old))


def _compute_edit(args: dict, ctx: ToolContext) -> tuple[Path, str, str]:
    """Validate the edit(s) and return (path, new_content, unified_diff).

    Applies each edit in order to a working copy, so both the preview and the
    apply step share one source of truth. Raises ToolError if the file is
    missing or any edit cannot be applied.
    """
    path = resolve_in_root(args["path"], ctx.project_root)
    if not path.exists():
        raise ToolError(f"File not found: {args['path']}")

    original = path.read_text(encoding="utf-8", errors="replace")
    updated = original
    for old, new in _coerce_edits(args):
        updated = _apply_one_edit(updated, old, new)
    if updated == original:
        raise ToolError("The edit(s) produced no change to the file.")

    diff = "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile=args["path"],
            tofile=args["path"],
        )
    )
    return path, updated, diff


def _edit_preview(args: dict, ctx: ToolContext) -> str:
    _, _, diff = _compute_edit(args, ctx)
    return diff or "[no visible change]"


def _edit_file(args: dict, ctx: ToolContext) -> str:
    path, updated, _ = _compute_edit(args, ctx)
    try:
        path.write_text(updated, encoding="utf-8")
    except OSError as e:
        raise ToolError(f"Could not write {args['path']}: {e}") from e
    n = len(_coerce_edits(args))
    return f"Edited {args['path']}." if n == 1 else f"Edited {args['path']} ({n} edits)."


def tools() -> list[Tool]:
    return [
        Tool(
            name="read_file",
            description="Read a text file and return its contents. Always read a "
            "file before editing it.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path relative to the project root."},
                    "offset": {"type": "integer", "description": "0-based line to start from (optional)."},
                    "limit": {"type": "integer", "description": "Max number of lines to read (optional)."},
                },
                "required": ["path"],
            },
            handler=_read_file,
        ),
        Tool(
            name="list_dir",
            description="List the entries of a directory. Directories end with '/'.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path (default '.')."},
                },
                "required": [],
            },
            handler=_list_dir,
        ),
        Tool(
            name="write_file",
            description="Create a NEW file with the given content. Fails if the "
            "file already exists (use edit_file for existing files).",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
            handler=_write_file,
            requires_confirmation=True,
            preview=_write_preview,
        ),
        Tool(
            name="edit_file",
            description="Replace text in an existing file. old_string must appear "
            "in the file and be unique (whitespace differences are tolerated). "
            "Read the file first. To change several places at once, pass an "
            "'edits' list instead of old_string/new_string.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_string": {"type": "string", "description": "Exact text to replace (must be unique in the file)."},
                    "new_string": {"type": "string", "description": "Replacement text."},
                    "edits": {
                        "type": "array",
                        "description": "Optional batch: apply several edits in order. "
                        "Use this instead of old_string/new_string to change "
                        "multiple places in one call.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "old_string": {"type": "string"},
                                "new_string": {"type": "string"},
                            },
                            "required": ["old_string", "new_string"],
                        },
                    },
                },
                "required": ["path"],
            },
            handler=_edit_file,
            requires_confirmation=True,
            preview=_edit_preview,
        ),
    ]
