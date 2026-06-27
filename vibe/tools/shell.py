"""run_bash: execute a shell command in the project root.

This is the most powerful (and dangerous) tool, so it always requires
confirmation unless the session is in auto-approve mode. Output is captured and
truncated before being handed back to the model.
"""

from __future__ import annotations

import subprocess

from ..errors import ToolError
from .base import Tool, ToolContext

TIMEOUT_SECONDS = 120
MAX_OUTPUT_CHARS = 20_000


def _run_bash_preview(args: dict, ctx: ToolContext) -> str:
    return f"$ {args.get('command', '')}"


def _run_bash(args: dict, ctx: ToolContext) -> str:
    command = args.get("command", "")
    if not command.strip():
        raise ToolError("command must not be empty.")
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=str(ctx.project_root),
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        raise ToolError(f"Command timed out after {TIMEOUT_SECONDS}s.")
    except OSError as e:
        raise ToolError(f"Could not run command: {e}") from e

    output = (proc.stdout or "") + (proc.stderr or "")
    if len(output) > MAX_OUTPUT_CHARS:
        output = output[:MAX_OUTPUT_CHARS] + "\n... [output truncated]"
    status = f"[exit code {proc.returncode}]"
    return f"{status}\n{output}".strip()


def tools() -> list[Tool]:
    return [
        Tool(
            name="run_bash",
            description="Run a shell command in the project root and return its "
            "combined stdout/stderr and exit code. Use for running tests, "
            "builds, git, etc.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The shell command to run."},
                },
                "required": ["command"],
            },
            handler=_run_bash,
            requires_confirmation=True,
            preview=_run_bash_preview,
        ),
    ]
