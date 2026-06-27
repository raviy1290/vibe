"""Shared exception types (kept in a leaf module to avoid import cycles)."""

from __future__ import annotations


class ToolError(Exception):
    """Raised by a tool when it cannot complete the requested action.

    The agent loop catches this and feeds the message back to the model as the
    tool result, so the model can recover (e.g. re-read a file, fix a path)
    instead of the whole program crashing.
    """


class LLMError(Exception):
    """Raised when talking to Ollama fails (connection refused, bad response)."""
