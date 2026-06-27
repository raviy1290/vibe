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
# edit_file  (exact-string replace)
# --------------------------------------------------------------------------
def _compute_edit(args: dict, ctx: ToolContext) -> tuple[Path, str, str]:
    """Validate the edit and return (path, new_content, unified_diff).

    Raises ToolError if the file is missing, old_string is absent, or it is not
    unique — so both the preview and the apply step share one source of truth.
    """
    path = resolve_in_root(args["path"], ctx.project_root)
    old = args.get("old_string", "")
    new = args.get("new_string", "")
    if not path.exists():
        raise ToolError(f"File not found: {args['path']}")
    if old == "":
        raise ToolError("old_string must not be empty.")
    if old == new:
        raise ToolError("old_string and new_string are identical; nothing to change.")

    original = path.read_text(encoding="utf-8", errors="replace")
    count = original.count(old)
    if count == 0:
        raise ToolError(
            "old_string was not found in the file. Read the file again and copy "
            "the exact text (including whitespace) you want to replace."
        )
    if count > 1:
        raise ToolError(
            f"old_string appears {count} times; it must be unique. Include more "
            "surrounding context so it matches exactly one location."
        )

    updated = original.replace(old, new, 1)
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
    return f"Edited {args['path']}."


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
            description="Replace an exact string in an existing file. old_string "
            "must match the file exactly and be unique. Read the file first.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_string": {"type": "string", "description": "Exact text to replace (must be unique in the file)."},
                    "new_string": {"type": "string", "description": "Replacement text."},
                },
                "required": ["path", "old_string", "new_string"],
            },
            handler=_edit_file,
            requires_confirmation=True,
            preview=_edit_preview,
        ),
    ]
