# vibe

**A tiny coding assistant for your terminal that runs 100% on your own machine.**
No cloud, no API keys, nothing leaving your laptop — it drives a local
[Ollama](https://ollama.com) model to read, edit, and run code for you.

Think of it as a stripped-down, open "Claude Code" you can read end to end: the
agent loop, the tools, the prompt, and the safety checks are all a few hundred
lines of plain Python.

## What it looks like

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

You type a request in plain English. vibe figures out which files to touch,
**shows you a diff and asks before changing anything**, then runs your tests to
check its own work.

## What you need

- **Python 3.11+**
- **[Ollama](https://ollama.com)** running locally (free, offline)

## Setup (about 2 minutes)

```bash
# 1. download a model that's good at tool-calling (this is the default)
ollama pull qwen2.5-coder:7b

# 2. install vibe in a virtual environment
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

Then run `vibe` from inside any project folder.

## Using it

```bash
vibe                      # start an interactive chat in the current folder
vibe "list the files"     # run a single request, then exit
vibe --model llama3.2     # use a different local model
vibe --auto               # don't ask before each change (handy for throwaway code)
```

Inside a session, type a slash command:

| Command | What it does |
|---------|--------------|
| `/help` | list all commands |
| `/tools` | show what the agent can do |
| `/model [name]` | switch model (`/model list` to see options) |
| `/auto` | toggle skipping confirmations |
| `/clear` | start a fresh conversation |
| `/exit` | quit (or press Ctrl-D) |

> 📖 **New here?** [USEME.md](USEME.md) is a full, step-by-step walkthrough that
> builds a real little app from scratch.

## How it works

At its core, vibe runs **one simple loop** (see
[`vibe/agent/loop.py`](vibe/agent/loop.py)):

1. Send your message + the list of available tools to the local model.
2. The model replies — with text, and/or a request to use a tool.
3. vibe runs each tool, asking you first for anything that writes or runs code.
4. The result is fed back to the model, and the loop repeats — until the model
   has nothing left to do.

The model never touches your files directly. It can only ask to use one of
**six small tools**: `read_file`, `list_dir`, `grep`, `write_file`,
`edit_file`, and `run_bash`.

### Why it's reliable on small local models

Small models are easy to trip up, so vibe makes a few deliberate choices:

- **Edits are exact find-and-replace, not full rewrites** — the model swaps one
  specific snippet, so it can't accidentally mangle the rest of a file.
- **It must read a file before editing it** (enforced in the prompt).
- **It stays inside your project folder** — any attempt to touch a file outside
  is blocked before it happens.
- **It works in front of you** — every write, edit, or command shows a preview
  and waits for your `y`.

## What's in the box

| File | Role |
|------|------|
| [`vibe/agent/loop.py`](vibe/agent/loop.py) | the send → run tools → repeat loop |
| [`vibe/agent/prompt.py`](vibe/agent/prompt.py) | the rules the agent follows |
| [`vibe/llm/ollama.py`](vibe/llm/ollama.py) | talks to Ollama over HTTP |
| [`vibe/tools/`](vibe/tools/) | the six tools the agent can use |
| [`vibe/safety.py`](vibe/safety.py) | keeps file access inside the project |
| [`vibe/ui/`](vibe/ui/) | the terminal chat, diffs, and slash commands |

## Configuration

Change the defaults with environment variables (`OLLAMA_HOST`, `VIBE_MODEL`) or
a `~/.vibe/config.json` file.

## Running the tests

```bash
pip install -e ".[dev]"
pytest                    # tests the tools + safety layer — no Ollama needed
```
