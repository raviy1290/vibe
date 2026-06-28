"""Entry point: `python -m vibe` (or the `vibe` console script).

Wires up config → Ollama client → tools → agent → REPL. With a positional
PROMPT argument it runs a single turn and exits (handy for scripting / testing);
otherwise it starts the interactive REPL.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .agent.loop import Agent
from .config import Config
from .errors import LLMError
from .llm.ollama import OllamaClient
from .tools.base import ToolContext, build_default_registry
from .trace import Tracer, build_tracer, default_trace_path
from .ui.render import UI
from .ui.repl import Repl


def build_session(config: Config,
                  tracer: Tracer | None = None) -> tuple[Agent, UI, OllamaClient]:
    ui = UI()
    client = OllamaClient(config.ollama_host, config.model, config.temperature)
    ctx = ToolContext(project_root=config.project_root, config=config)
    registry = build_default_registry(ctx)
    agent = Agent(client, registry, ctx, ui, tracer=tracer)
    return agent, ui, client


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vibe", description=__doc__)
    parser.add_argument("prompt", nargs="*", help="run a single prompt and exit")
    parser.add_argument("--model", help="Ollama model to use")
    parser.add_argument("--host", help="Ollama host URL")
    parser.add_argument("--auto", action="store_true",
                        help="auto-approve writes/edits/bash (no confirmations)")
    parser.add_argument("-v", "--verbose", action="count", default=0,
                        help="trace the reasoning loop (-v readable, -vv full payloads)")
    parser.add_argument("--trace", nargs="?", const="", default=None, metavar="PATH",
                        help="write a JSONL reasoning trace "
                             "(default ~/.vibe/traces/session-<ts>.jsonl)")
    ns = parser.parse_args(argv)

    config = Config.load()
    if ns.model:
        config.model = ns.model
    if ns.host:
        config.ollama_host = ns.host
    if ns.auto:
        config.auto_approve = True

    trace_file = None
    if ns.trace is not None:
        trace_file = Path(ns.trace) if ns.trace else default_trace_path()
    tracer = build_tracer(verbosity=ns.verbose, trace_file=trace_file)

    agent, ui, client = build_session(config, tracer=tracer)
    if trace_file is not None:
        ui.info(f"tracing reasoning to {trace_file}")
    try:
        if ns.prompt:
            agent.run_turn(" ".join(ns.prompt))
            return 0
        Repl(agent, ui, client).run()
        return 0
    except LLMError as e:
        ui.error(str(e))
        return 1
    finally:
        tracer.close()
        client.close()


if __name__ == "__main__":
    sys.exit(main())
