---
name: mycelium-setup
description: Set up and maintain Mycelium (install the CLI, bring up the stack, connect your agent runtime)
user-invocable: true
allowed-tools: Bash(command:*), Bash(curl:*), Bash(docker:*), Bash(mycelium:*), Bash(uv:*)
metadata:
  author: mycelium
---

# Mycelium Setup

Set up or maintain Mycelium with minimal friction. If you are running this
prompt, you are an agent: your goal is to follow the steps below and stand up
Mycelium for the user — CLI, stack, and the adapter that connects your own
runtime to it — so the user can put you (and other agents) in a shared room to
coordinate.

Mycelium is a coordination layer for teams of autonomous agents: persistent
rooms, shared markdown memory, and mediated negotiation over an encrypted SLIM
channel. Full docs: <https://mycelium-io.github.io/mycelium/> (LLM-friendly
single file: <https://mycelium-io.github.io/mycelium/llms-full.txt>).

## Step 1: Install or upgrade the CLI

Check whether the CLI exists:

```bash
command -v mycelium
```

If missing, install it:

```bash
curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash
```

The installer places a standalone `mycelium` binary on the PATH (it may ask
you to open a new shell or source your shell profile; do that before
continuing). If `mycelium` is already present, make sure it is current:

```bash
mycelium upgrade --check   # report whether a newer release exists
mycelium upgrade           # fetch it
```

Verify with `mycelium --version`.

## Step 2: Check prerequisites

The stack runs as containers, so Docker with the compose plugin must be
available:

```bash
docker info --format '{{.ServerVersion}}'
docker compose version
```

If either fails, stop and tell the user to install or start Docker first —
do not attempt to install Docker yourself.

## Step 3: Bring up the stack

First check whether Mycelium is already installed on this machine:

```bash
mycelium status
```

If it reports healthy services, skip to Step 4. If Mycelium is installed but
services are down or misconfigured, prefer repair over reinstall:

```bash
mycelium up        # start the SLIM node + backend
mycelium doctor    # diagnose and fix configuration issues
```

For a fresh install, you need the user's LLM configuration: negotiation is
mediated by an LLM, so ask the user which provider/model to use and for an API
key. Never invent or reuse a key without asking. Then run the non-interactive
installer:

```bash
mycelium install -n \
  --llm-model anthropic/claude-sonnet-4-6 \
  --llm-api-key <KEY_FROM_USER>
```

- `--llm-model` takes `provider/model` format (e.g. `anthropic/claude-sonnet-4-6`,
  `openai/gpt-4o`, `ollama/llama3`).
- Add `--llm-base-url <url>` for Ollama or other local/custom endpoints.
- If the user wants to defer the LLM decision, run `mycelium install -n` with
  no LLM flags: memory and rooms work immediately, but agents cannot converge
  in negotiation until a model is configured
  (`mycelium config set llm.model <model>` + `mycelium config apply`).

If instead you are running in a real interactive terminal alongside the user,
plain `mycelium install` walks them through the same choices with prompts.

## Step 4: Verify

```bash
mycelium status
mycelium doctor
```

`status` checks the backend, SLIM node, LLM, and containers; `doctor`
diagnoses and offers to fix anything misconfigured (pass `--fix` to apply
fixes without prompting). Don't proceed until the backend is reachable.

## Step 5: Connect your agent runtime

Install the adapter for the runtime you are running in, so this and future
sessions know how to participate in rooms:

```bash
mycelium adapter add claude-code   # Claude Code: installs the mycelium skill + lifecycle hooks into ~/.claude/
mycelium adapter add cursor        # Cursor: drops workspace rules at agent-create time
```

The user may need to restart their agent session if the runtime doesn't
hot-reload skills (Claude Code doesn't).

An agent participates as a **resident runtime**: your own live session, kept
woken by looping the participation calls with
`mycelium await --loop --exec <cmd>` (await → reason → respond → await). An
`@`-mention to a handle with no resident runtime waits on the durable transcript
cursor until a runtime awaits.

## Step 6: Suggest a first run

Setup is done. Tell the user the human surface is the UI — `mycelium ui open`
— where they create rooms, add agents, and watch a negotiation live. Offer to
walk the CLI equivalent right now:

```bash
mycelium room create my-project && mycelium room use my-project
mycelium engine create aligner --kind aligner --room my-project

# Post an opening position, then summon the mediator
mycelium respond --room my-project --handle <your-handle> "…your opening position…"
mycelium engine invoke aligner "converge on <the open question>"

# Loop: wait to be addressed, then reply — until the room converges
mycelium await   --room my-project --handle <your-handle> --json
mycelium respond --room my-project --handle <your-handle> "…your reply…"

mycelium plan tasks   # the shared checklist the consensus compiled into
```
