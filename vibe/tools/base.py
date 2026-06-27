"""Tool registry and the small contract every tool follows.

A Tool is:
  - metadata the model sees (name, description, JSON-schema parameters)
  - a ``handler(args, ctx) -> str`` that does the work and returns a result string
  - optionally ``requires_confirmation`` + a ``preview(args, ctx) -> str`` used to
    show the user what will happen (a diff, a command) before it runs.

The result string is what gets fed back to the model, so it should be concise
and informative.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..config import Config

# handler/preview signature
Handler = Callable[[dict, "ToolContext"], str]
Preview = Callable[[dict, "ToolContext"], str]


@dataclass
class ToolContext:
    """Everything a tool needs from the running session."""
    project_root: Path
    config: Config


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict  # JSON schema for the arguments object
    handler: Handler
    requires_confirmation: bool = False
    preview: Preview | None = None

    def schema(self) -> dict:
        """The OpenAI/Ollama function-tool schema for this tool."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def schemas(self) -> list[dict]:
        return [t.schema() for t in self._tools.values()]


def build_default_registry(ctx: ToolContext) -> ToolRegistry:
    """Register the MVP tool set. Imported here (not at module top) to keep the
    tool modules free to import from base without a cycle."""
    from . import files, search, shell

    registry = ToolRegistry()
    for tool in (
        *files.tools(),
        *search.tools(),
        *shell.tools(),
    ):
        registry.register(tool)
    return registry
