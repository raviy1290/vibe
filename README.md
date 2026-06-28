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
vibe -v                   # show the reasoning trace live (-vv for full detail)
vibe --trace              # also save a replayable JSONL trace of the session
```

Inside a session, type a slash command:

| Command | What it does |
|---------|--------------|
| `/help` | list all commands |
| `/tools` | show what the agent can do |
| `/model [name]` | switch model (`/model list` to see options) |
| `/auto` | toggle skipping confirmations |
| `/verbose [0-2]` | set the live reasoning trace level |
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

- **Edits are find-and-replace, not full rewrites** — the model swaps one
  specific snippet, so it can't accidentally mangle the rest of a file. Small
  indentation/whitespace slips are tolerated, and a near-miss gets a *"did you
  mean this line?"* hint so the model can fix it in one step instead of looping.
- **Several edits in one call** — it can batch multiple find-and-replaces into a
  single `edit_file`, so multi-part changes don't dissolve into a loop.
- **It plans before multi-step work** — for anything beyond a one-liner it
  writes a short numbered plan first, then executes it step by step.
- **It must read a file before editing it** (enforced in the prompt).
- **It stays inside your project folder** — any attempt to touch a file outside
  is blocked before it happens.
- **It works in front of you** — every write, edit, or command shows a preview
  and waits for your `y`.

## Watching the model reason

These local models have no hidden "thoughts" — their reasoning *is* the text they
emit plus the sequence of tools they choose. `vibe` can show you that trajectory:

```bash
vibe -v "summarise tasks.py"     # readable trace on stderr
vibe -vv ...                     # full payloads (messages sent, raw replies)
vibe --trace ...                 # write a JSONL record you can replay/grep/diff
```

Each step is logged as an **intent → action → observation** triple — what the
model *said*, the tool call that became, and the result fed back in:

```
→ POST /api/chat  model=qwen2.5-coder:7b  msgs=3  tools=6
← reply  prompt=412 tok  gen=58 tok  1.9s
  reasoning: I'll read tasks.py first to see the list loop.
  → read_file({"path": "tasks.py"})  (native)
  ✓ read_file → 612 chars fed back
decision: final answer — no tool calls
```

One thing to keep in mind: a small model's prose isn't always *why* it acted, so
trust the **actions and their results** as ground truth and read the reasoning
text as a hint.

## What's in the box

| File | Role |
|------|------|
| [`vibe/agent/loop.py`](vibe/agent/loop.py) | the send → run tools → repeat loop |
| [`vibe/agent/prompt.py`](vibe/agent/prompt.py) | the rules the agent follows |
| [`vibe/llm/ollama.py`](vibe/llm/ollama.py) | talks to Ollama over HTTP |
| [`vibe/tools/`](vibe/tools/) | the six tools the agent can use |
| [`vibe/safety.py`](vibe/safety.py) | keeps file access inside the project |
| [`vibe/trace.py`](vibe/trace.py) | the reasoning trace (live `-v` view + JSONL) |
| [`vibe/ui/`](vibe/ui/) | the terminal chat, diffs, and slash commands |

## Configuration

Change the defaults with environment variables (`OLLAMA_HOST`, `VIBE_MODEL`) or
a `~/.vibe/config.json` file.

## Running the tests

```bash
pip install -e ".[dev]"
pytest                    # tests the tools + safety layer — no Ollama needed
```
