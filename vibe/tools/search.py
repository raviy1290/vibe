"""grep: search the project for a pattern. Uses ripgrep when available (fast,
respects .gitignore) and falls back to a pure-Python walk otherwise."""

from __future__ import annotations

import os
import re
import shutil
import subprocess

from ..errors import ToolError
from ..safety import resolve_in_root
from .base import Tool, ToolContext
from .files import SKIP_DIRS

MAX_MATCHES = 200


def _grep(args: dict, ctx: ToolContext) -> str:
    pattern = args.get("pattern", "")
    if not pattern:
        raise ToolError("pattern must not be empty.")
    root = resolve_in_root(args.get("path", "."), ctx.project_root)

    rg = shutil.which("rg")
    if rg:
        return _grep_ripgrep(rg, pattern, root)
    return _grep_python(pattern, root)


def _grep_ripgrep(rg: str, pattern: str, root) -> str:
    try:
        proc = subprocess.run(
            [rg, "--line-number", "--no-heading", "--color", "never", pattern, str(root)],
            capture_output=True, text=True, timeout=30,
        )
    except (subprocess.SubprocessError, OSError) as e:
        raise ToolError(f"ripgrep failed: {e}") from e
    if proc.returncode not in (0, 1):  # 1 == no matches, which is fine
        raise ToolError(proc.stderr.strip() or "ripgrep error")
    lines = proc.stdout.splitlines()
    return _format(lines)


def _grep_python(pattern: str, root) -> str:
    try:
        regex = re.compile(pattern)
    except re.error as e:
        raise ToolError(f"Invalid regex: {e}") from e
    matches: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            full = os.path.join(dirpath, name)
            try:
                with open(full, "r", encoding="utf-8", errors="strict") as fh:
                    for i, line in enumerate(fh, 1):
                        if regex.search(line):
                            matches.append(f"{full}:{i}:{line.rstrip()}")
                            if len(matches) >= MAX_MATCHES + 1:
                                return _format(matches)
            except (UnicodeDecodeError, OSError):
                continue  # skip binaries / unreadable files
    return _format(matches)


def _format(lines: list[str]) -> str:
    if not lines:
        return "No matches found."
    truncated = len(lines) > MAX_MATCHES
    shown = lines[:MAX_MATCHES]
    out = "\n".join(shown)
    if truncated:
        out += f"\n... [showing first {MAX_MATCHES} matches]"
    return out


def tools() -> list[Tool]:
    return [
        Tool(
            name="grep",
            description="Search for a regular-expression pattern across files in "
            "the project. Returns matching lines as path:line:text.",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex to search for."},
                    "path": {"type": "string", "description": "Directory or file to search (default '.')."},
                },
                "required": ["pattern"],
            },
            handler=_grep,
        ),
    ]
