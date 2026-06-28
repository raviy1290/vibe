# Example: build a small app with `vibe`, end to end

This walks you from a fresh machine to **vibe-coding a real little project** with a
local model — no cloud, no API keys. It has two parts:

1. [Setup](#part-1--setup) — get Ollama + `vibe` running.
2. [Coding example](#part-2--coding-example-a-tasks-cli) — drive `vibe` to build a
   command-line task tracker, step by step.

---

## Part 1 — Setup

### 1. Prerequisites — check Python and start Ollama

You need **Python 3.11+** and a running **[Ollama](https://ollama.com)** server.
Run these in order:

```bash
python3 --version    # must print 3.11 or newer
ollama serve         # start Ollama; leave running in its own terminal (skip if it auto-starts)
```

### 2. Pull a model — download the local LLM vibe drives

`vibe` defaults to `qwen2.5-coder:7b` (a good tool-caller). Any tool-capable
local model works; a bigger coder does noticeably better on multi-step tasks if
your RAM allows. Run in order:

```bash
ollama pull qwen2.5-coder:7b     # default model — pull this one
ollama pull qwen2.5-coder:14b    # optional: bigger/better (or :32b), needs more RAM
ollama list                      # confirm which models you now have
```

### 3. Install `vibe` — create a virtualenv and install the package

Run from the project root ([the repo with this file](.)), in order:

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"            # installs httpx, rich, prompt_toolkit, pytest
```

### 4. Smoke-test it — confirm vibe reaches Ollama and can run a tool

`--auto` skips the write/edit/bash confirmations (fine for a throwaway test).
You should see the agent call `list_dir` and summarize; if you instead get
*"Could not reach Ollama"*, the server isn't running (go back to `ollama serve`
in step 1). Run in order:

```bash
vibe --auto "list the files in this directory"   # smoke test: agent calls list_dir, then summarizes
pytest -q                                         # optional: run unit tests (no Ollama needed)
```

---

## Part 2 — Coding example: a "tasks" CLI

Goal: build `tasks.py`, a CLI that stores tasks in a JSON file and supports
`add`, `list`, and `done`. We'll build it in small steps and let `vibe` run the
program to verify each one — the same rhythm you'd use on a real codebase.

### Step 0 — start a clean project

Do this in a **separate directory** so the agent's sandbox is just this app:

```bash
mkdir ~/tasks-app && cd ~/tasks-app
vibe
```

`vibe` opens a REPL scoped to `~/tasks-app`. It can only touch files inside it.

> Tip: type `/help` to see commands, `/tools` to list what the agent can do,
> `/model list` to switch models mid-session.

> **The transcripts below are real**, captured from `qwen2.5-coder:7b` with
> `vibe --auto` (auto-approve, so the confirmation prompts are skipped). In an
> interactive `vibe` session you'd see a `Apply write_file? [y/N]` prompt with a
> diff before each write/edit/bash — press `y` to apply.

### Step 1 — scaffold the CLI

At the `you ›` prompt, type:

```
Create tasks.py: a CLI using argparse with three subcommands — add <text>,
list, and done <index>. Store tasks as a JSON list in tasks.json next to the
script. Print a friendly message after each action.
```

The model emits a tool call (note: local models fence it as ```` ```json ````
or even ```` ```bash ````; vibe parses it either way) and the file is written:

```
vibe › ```json
{"name": "write_file", "arguments": {"path": "tasks.py", "content": "..."}}
```
  → write_file(path=tasks.py, content=#!/usr/bin/env python3\nimport argparse…)
╭─ write_file result ──────────────────────────────────────────╮
│ Created tasks.py (46 lines).                                 │
╰──────────────────────────────────────────────────────────────╯

vibe › Great! The `tasks.py` file has been created with the specified
functionality.
```

### Step 2 — run it

```
Run: python3 tasks.py add "buy milk"   then run: python3 tasks.py list
```

Real output — two `run_bash` calls, and a new `tasks.json` on disk:

```
  → run_bash(command=python3 tasks.py add "buy milk")
╭─ run_bash result ────────────────────────────────────────────╮
│ [exit code 0]                                                │
│ Task added: buy milk                                         │
╰──────────────────────────────────────────────────────────────╯
  → run_bash(command=python3 tasks.py list)
╭─ run_bash result ────────────────────────────────────────────╮
│ [exit code 0]                                                │
│ 0: buy milk                                                  │
╰──────────────────────────────────────────────────────────────╯

vibe › Task added and listed successfully.
```

### Step 3 — change existing code (the reliable-edit path)

This exercises `edit_file`. Keep the edit **small and specific** — that's what a
7B model does reliably (see [the reality note](#a-note-on-local-model-reality)):

```
Read tasks.py. Then make ONE edit to the list output so each task prints as
"- [N] task" instead of "N: task" (change only the f-string in the list loop).
Then run python3 tasks.py list once to verify.
```

Real output — `read_file` → `edit_file` (exact-string swap) → `run_bash`:

```
  → read_file(path=tasks.py)
  → edit_file(path=tasks.py,
       old_string=print(f'{i}: {task}'),
       new_string=print(f'- [{i}] {task}'))
╭─ edit_file result ───────────────────────────────────────────╮
│ Edited tasks.py.                                             │
╰──────────────────────────────────────────────────────────────╯
  → run_bash(command=python3 tasks.py list)
╭─ run_bash result ────────────────────────────────────────────╮
│ [exit code 0]                                                │
│ - [0] buy milk                                               │
╰──────────────────────────────────────────────────────────────╯

vibe › The change has been verified.
```

### Step 4 — add a test and run it

```
Create test_tasks.py: a pytest test that uses subprocess to run
"python3 tasks.py add hello" then "python3 tasks.py list" and asserts "hello"
appears in the list output. Then run: python3 -m pytest -q
```

Real output — `write_file` → `run_bash`, and the test passes:

```
  → write_file(path=test_tasks.py, content=# test_tasks.py\nimport subprocess…)
╭─ write_file result ──────────────────────────────────────────╮
│ Created test_tasks.py (13 lines).                            │
╰──────────────────────────────────────────────────────────────╯
  → run_bash(command=python3 -m pytest -q)
╭─ run_bash result ────────────────────────────────────────────╮
│ [exit code 0]                                                │
│ .                                              [100%]        │
│ 1 passed in 0.11s                                            │
╰──────────────────────────────────────────────────────────────╯
```

### Step 5 — keep vibing

From here, just describe what you want next, e.g.:

- `Read tasks.py, then change the "Task added" message to "Added ✓".`
- `Write a short README.md documenting the add/list/done commands.`
- `Add a "count" subcommand that prints how many tasks there are.`

When you're done, press **Ctrl-D** (or `/exit`).

### A note on local-model reality

Everything above was run on `qwen2.5-coder:7b` and **works as shown**. The size
of the model still matters for the size of the edit. Originally, when this same
example asked the 7B model for a *conditional-logic* edit ("add a `--json` flag
that prints JSON when set"), it added the argparse flag but then **looped**
trying to wire the `if` branch and hit vibe's 25-iteration safety cap without
finishing.

vibe has since gained three changes aimed squarely at that failure mode:
- **Batched edits** — `edit_file` accepts an `edits` list, so a multi-part
  change (add the flag *and* wire the `if`) goes in one call instead of several
  fragile round-trips.
- **Whitespace-tolerant matching** — an `old_string` whose indentation or
  trailing spaces are slightly off still matches, and a near-miss returns the
  closest line as a hint, so the model recovers in one step.
- **Plan-first** — for anything multi-step the agent drafts a short numbered
  plan before touching code, which keeps it from drifting.

Together these make multi-part edits land far more often on 7B. Takeaways:
- 7B is reliable for **create a file**, **run a command**, and **focused edits**
  (single or batched). Keep each step small and well-scoped.
- For the **hardest conditional edits**, a bigger model still helps: size up
  with `vibe --model qwen2.5-coder:14b` (no code changes).
- The 25-iteration cap is a feature — a stuck model stops instead of running
  forever.

---

## Getting good results (local-model tips)

- **One step at a time.** Small, verifiable asks ("add X, then run Y") beat
  "build the whole app". Local models drift on long, vague prompts.
- **Tell it to verify.** Ending a prompt with "then run …" makes the agent check
  its own work via `run_bash`.
- **Trust the diffs.** Every write/edit/bash shows a preview — actually read it
  before pressing `y`. It's your safety net.
- **Use `/auto` sparingly.** Great for a scratch project, risky on real code.
- **Batch related edits.** For a multi-part change, vibe can apply several
  find-and-replaces in one `edit_file` call (an `edits` list) — more reliable
  than many separate edits. Small whitespace differences are tolerated, and a
  near-miss suggests the closest line (see the reality note above).
- **If it feels dumb, size up the model:** `/model qwen2.5-coder:14b` mid-session,
  or launch with `vibe --model qwen2.5-coder:14b`. No code changes needed.
- **Different models, same agent.** `llama3.2` uses native tool-calls;
  `qwen2.5-coder` emits its calls in a ```` ```json ```` / ```` ```bash ````
  fence — vibe's parser accepts any fence by JSON shape, so both just work.

## Command reference

| Action | How |
|--------|-----|
| Start REPL in current dir | `vibe` |
| One-shot prompt | `vibe "your prompt"` |
| Pick a model | `vibe --model llama3.2` |
| Skip confirmations | `vibe --auto` |
| Point at a remote Ollama | `vibe --host http://HOST:11434` |
| Trace the reasoning live | `vibe -v` (readable) / `vibe -vv` (full payloads) |
| Save a replayable trace | `vibe --trace` (JSONL in `~/.vibe/traces/`) |
| In-session: help / tools | `/help`, `/tools` |
| In-session: switch model | `/model NAME` (or `/model list`) |
| In-session: toggle auto-approve | `/auto` |
| In-session: set trace level | `/verbose 0\|1\|2` |
| In-session: clear history | `/clear` |
| In-session: quit | `/exit` or Ctrl-D |

Config also reads `OLLAMA_HOST` / `VIBE_MODEL` env vars and
`~/.vibe/config.json`.
