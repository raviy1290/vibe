"""All terminal rendering goes through the UI class so the agent loop stays
free of print statements. Uses `rich` for colour, diffs and panels."""

from __future__ import annotations

import json

from rich.console import Console
from rich.panel import Panel
from rich.text import Text


class UI:
    def __init__(self) -> None:
        self.console = Console()
        self._mid_stream = False

    # -- banner / misc -----------------------------------------------------

    def banner(self, model: str, root: str) -> None:
        self.console.print(
            Panel.fit(
                Text.assemble(
                    ("vibe ", "bold magenta"),
                    ("— local coding agent\n", "magenta"),
                    (f"model: {model}\n", "dim"),
                    (f"cwd:   {root}\n", "dim"),
                    ("type /help for commands, Ctrl-D to quit", "dim"),
                ),
                border_style="magenta",
            )
        )

    def info(self, msg: str) -> None:
        self.console.print(msg, style="cyan")

    def warn(self, msg: str) -> None:
        self.console.print(f"⚠ {msg}", style="yellow")

    def error(self, msg: str) -> None:
        self.console.print(f"✗ {msg}", style="bold red")

    # -- streaming assistant text -----------------------------------------

    def stream_assistant(self, chunk: str) -> None:
        if not self._mid_stream:
            self.console.print("\n[bold magenta]vibe ›[/] ", end="")
            self._mid_stream = True
        self.console.print(chunk, end="", markup=False, highlight=False)

    def end_assistant(self) -> None:
        if self._mid_stream:
            self.console.print()  # close the streamed line
            self._mid_stream = False

    # -- tool calls --------------------------------------------------------

    def show_tool_call(self, name: str, args: dict) -> None:
        rendered = ", ".join(f"{k}={self._short(v)}" for k, v in args.items())
        self.console.print(f"  [dim]→ {name}({rendered})[/]")

    def show_tool_result(self, name: str, output: str, is_error: bool = False) -> None:
        style = "red" if is_error else "dim"
        preview = output if len(output) <= 800 else output[:800] + " …"
        body = Text(preview, style=style)
        self.console.print(Panel(body, title=f"{name} result", border_style=style,
                                 title_align="left"))

    # -- confirmation ------------------------------------------------------

    def confirm(self, name: str, preview: str | None) -> bool:
        if preview is not None:
            self.console.print(self._format_preview(name, preview))
        try:
            answer = self.console.input(
                f"  [bold yellow]Apply {name}?[/] [y/N] "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            self.console.print()
            return False
        return answer in ("y", "yes")

    def _format_preview(self, name: str, preview: str) -> Panel:
        body = Text()
        for line in preview.splitlines():
            if line.startswith(("+++", "---")):
                body.append(line + "\n", style="bold")
            elif line.startswith("@@"):
                body.append(line + "\n", style="cyan")
            elif line.startswith("+"):
                body.append(line + "\n", style="green")
            elif line.startswith("-"):
                body.append(line + "\n", style="red")
            elif line.startswith("$"):
                body.append(line + "\n", style="yellow")
            else:
                body.append(line + "\n")
        return Panel(body, title=f"proposed: {name}", border_style="yellow",
                     title_align="left")

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _short(value, limit: int = 60) -> str:
        try:
            s = value if isinstance(value, str) else json.dumps(value)
        except (TypeError, ValueError):
            s = str(value)
        s = s.replace("\n", "\\n")
        return s if len(s) <= limit else s[:limit] + "…"
