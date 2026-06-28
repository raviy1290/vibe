"""The read-eval-print loop: reads user input, handles slash commands, and hands
everything else to the agent. Uses prompt_toolkit for history + line editing."""

from __future__ import annotations

from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory

from ..agent.loop import Agent
from ..errors import LLMError
from ..llm.ollama import OllamaClient
from .render import UI

HISTORY_PATH = Path.home() / ".vibe" / "history"

HELP = """\
Commands:
  /help            show this help
  /tools           list available tools
  /model [name]    show or switch the Ollama model (/model list to enumerate)
  /auto            toggle auto-approve (skip confirmations) for this session
  /verbose [0-2]   set the live reasoning trace level (0 off, 1 readable, 2 full)
  /clear           clear the conversation history
  /exit, /quit     leave vibe (or press Ctrl-D)
Anything else is sent to the agent.\
"""


class Repl:
    def __init__(self, agent: Agent, ui: UI, client: OllamaClient):
        self.agent = agent
        self.ui = ui
        self.client = client
        self.config = agent.ctx.config
        HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.session: PromptSession = PromptSession(history=FileHistory(str(HISTORY_PATH)))

    def run(self) -> None:
        self.ui.banner(self.config.model, str(self.config.project_root))
        while True:
            try:
                text = self.session.prompt("\nyou › ").strip()
            except EOFError:
                break  # Ctrl-D
            except KeyboardInterrupt:
                continue  # Ctrl-C cancels the current line
            if not text:
                continue
            if text.startswith("/"):
                if not self._command(text):
                    break
                continue
            try:
                self.agent.run_turn(text)
            except KeyboardInterrupt:
                self.ui.end_assistant()
                self.ui.warn("interrupted")
            except LLMError as e:
                self.ui.end_assistant()
                self.ui.error(str(e))
        self.ui.info("bye 👋")

    # -- slash commands ----------------------------------------------------

    def _command(self, text: str) -> bool:
        parts = text.split()
        cmd, args = parts[0], parts[1:]
        if cmd in ("/exit", "/quit"):
            return False
        elif cmd == "/help":
            self.ui.console.print(HELP)
        elif cmd == "/tools":
            for name in self.agent.registry.names():
                tool = self.agent.registry.get(name)
                self.ui.console.print(f"  [bold]{name}[/] — {tool.description}")
        elif cmd == "/auto":
            self.config.auto_approve = not self.config.auto_approve
            state = "ON" if self.config.auto_approve else "OFF"
            self.ui.warn(f"auto-approve is now {state}")
        elif cmd == "/verbose":
            level = int(args[0]) if args and args[0].isdigit() else 1
            self.agent.tracer.set_console_level(level)
            self.ui.warn(f"reasoning trace level = {min(level, 2)}")
        elif cmd == "/clear":
            self.agent.reset()
            self.ui.info("conversation cleared")
        elif cmd == "/model":
            self._model_command(args)
        else:
            self.ui.warn(f"unknown command: {cmd} (try /help)")
        return True

    def _model_command(self, args: list[str]) -> None:
        if not args:
            self.ui.info(f"current model: {self.config.model}")
            return
        if args[0] == "list":
            try:
                for name in self.client.list_models():
                    marker = " (current)" if name == self.config.model else ""
                    self.ui.console.print(f"  {name}{marker}")
            except LLMError as e:
                self.ui.error(str(e))
            return
        new_model = args[0]
        self.config.model = new_model
        self.client.model = new_model
        self.ui.info(f"switched to model: {new_model}")
