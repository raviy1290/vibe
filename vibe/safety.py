"""The safety layer: keep file access inside the project root.

Confirmation prompting lives in the UI (ui/render.py) because it needs to draw
diffs and read keys; this module is pure path logic so it can be unit-tested.
"""

from __future__ import annotations

from pathlib import Path

from .errors import ToolError


def resolve_in_root(path: str, root: Path) -> Path:
    """Resolve ``path`` (possibly relative to ``root``) and guarantee the result
    stays inside ``root``. Raises ToolError on any attempt to escape.

    This is the single chokepoint every file tool routes through, so a model
    asking to read ``../../etc/passwd`` or an absolute path outside the project
    is rejected before any I/O happens.
    """
    root = root.resolve()
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    if resolved != root and root not in resolved.parents:
        raise ToolError(
            f"Path {path!r} resolves outside the project root ({root}). "
            "Access is restricted to the current project."
        )
    return resolved
