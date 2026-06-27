"""The tools the agent is allowed to call. Each tool is plain Python; the
registry turns them into JSON-schema definitions for the model and dispatches
calls back to the handler."""

from .base import Tool, ToolContext, ToolRegistry, build_default_registry

__all__ = ["Tool", "ToolContext", "ToolRegistry", "build_default_registry"]
