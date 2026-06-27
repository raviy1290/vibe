# vibe

A small, **Claude-Code-like terminal coding agent that runs entirely on local
[Ollama](https://ollama.com)**. Built from scratch in Python to make every part
of an agentic coder legible: the agent loop, the tools, the prompt, the safety
layer.

```
you › add a /health endpoint to app.py and run the tests

vibe › I'll read app.py first.
  → read_file(path=app.py)
  → edit_file(path=app.py, old_string=…, new_string=…)
  ┌ proposed: edit_file ─────────────
  │ +@app.get("/health")
  │ +def health(): return {"ok": True}
  └──────────────────────────────────
  Apply edit_file? [y/N] y
  → run_bash(command=pytest -q)
vibe › Added the endpoint; 5 tests pass.
```

## How it works

One loop (see [`vibe/agent/loop.py`](vibe/agent/loop.py)):

1. send the conversation + tool schemas to Ollama
2. the model replies with text and/or tool calls
3. execute each tool (with a confirmation + diff for writes/edits/bash)
4. feed results back and repeat until the model stops calling tools

Reliability choices that matter for small local models:
- **Exact-string edits** (`edit_file`) instead of whole-file rewrites.
- **Read-before-edit** enforced in the system prompt.
- **Text-protocol fallback**: models without native tool-calling can emit a
  ```` ```tool {…}``` ```` block instead.

## Layout

| Path | Role |
|------|------|
| [`vibe/llm/ollama.py`](vibe/llm/ollama.py) | httpx client for `POST /api/chat` (streaming) |
| [`vibe/agent/loop.py`](vibe/agent/loop.py) | the send→execute→repeat loop |
| [`vibe/agent/prompt.py`](vibe/agent/prompt.py) | system prompt / behaviour rules |
| [`vibe/tools/`](vibe/tools/) | read_file, list_dir, grep, write_file, edit_file, run_bash |
| [`vibe/safety.py`](vibe/safety.py) | path sandbox (stay inside the project root) |
| [`vibe/ui/`](vibe/ui/) | streaming output, diffs, REPL + slash commands |

## Setup

```bash
ollama pull qwen2.5-coder:7b        # default model (supports tool calling)
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

## Run

```bash
vibe                      # interactive REPL in the current directory
vibe "list the files"     # one-shot prompt
vibe --model llama3.2     # pick another local model
vibe --auto               # skip confirmations (use with care)
```

Slash commands: `/help`, `/tools`, `/model [name|list]`, `/auto`, `/clear`, `/exit`.

Config via env (`OLLAMA_HOST`, `VIBE_MODEL`) or `~/.vibe/config.json`.

## Test

```bash
pip install -e ".[dev]"
pytest                    # tools + safety, no Ollama required
```
