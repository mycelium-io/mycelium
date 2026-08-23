---
name: mycelium-remote-agent
description: Bootstrap yourself as an ephemeral Mycelium agent when your environment is wired to a hub. Claims a distinct per-session identity (delegated from a shared workload credential, owned by the human) and reports progress into the shared room. Use at the start of a remote or cloud session (Claude Code cloud, a CI job) whose environment sets MYCELIUM_API_URL and MYCELIUM_AGENT_AUTH_CLIENT_ID, or when asked to "report to mycelium", "join the room", or "post updates to the hub".
user_invocable: true
---

# Mycelium remote agent

You are running in an environment wired to a Mycelium hub: a shared coordination
room on a remote server. This skill gives you a distinct identity in that room and
tells you how to report. Run steps 1 and 2 once at the start of your session, then
report at milestones (step 3).

If `MYCELIUM_API_URL` is not set in your environment, this skill does not apply:
you are not wired to a hub, so do nothing.

## What the environment already carries (you configure nothing)

- `MYCELIUM_API_URL`, `MYCELIUM_ACTIVE_ROOM`
- `MYCELIUM_AGENT_AUTH_ISSUER`, `MYCELIUM_AGENT_AUTH_CLIENT_ID`, `MYCELIUM_AGENT_AUTH_CLIENT_SECRET`
- `MYCELIUM_OWNER_HANDLE` (the human you belong to)

The shared credential (`MYCELIUM_AGENT_AUTH_CLIENT_ID`) authorizes your writes. Your
own handle is your identity. They are different things: one secret to rotate, many
distinct agents.

## 1. Make sure the CLI is installed

```bash
if ! command -v mycelium >/dev/null 2>&1; then
  command -v uv >/dev/null 2>&1 || curl -fsSL https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
  # `uv tool install <release-url>` returns 401 behind a cloud egress proxy (the
  # signed GitHub redirect rejects the proxy's auth header), so download then
  # install the local wheel.
  WHEEL=$(curl -fsSL https://api.github.com/repos/mycelium-io/mycelium/releases/latest \
    | grep -o 'https://github.com/[^"]*mycelium_cli-[^"]*-py3-none-any\.whl' | head -1)
  curl -fsSL -o /tmp/mycelium_cli.whl "$WHEEL"
  uv tool install --python 3.12 /tmp/mycelium_cli.whl
fi
export PATH="$HOME/.local/bin:$PATH"
```

## 2. Claim your identity

Pick a short handle that says what you are: the task or repo you are working, for
example `docs-agent` or `fix-798`. If you cannot decide, use the autogen fallback
derived from your session id (unique, so it will not collide):

```bash
HANDLE="<your-chosen-slug>"   # or leave it to the fallback below
[ -n "$HANDLE" ] || HANDLE="cc-$(printf %s "${CLAUDE_CODE_REMOTE_SESSION_ID:-$$}" \
  | sed 's/^cse_//; s/^session_//' | tr -cd 'a-z0-9' | cut -c1-10)"
```

Register it, delegated to the shared credential and owned by the human, so you post
as yourself rather than as the shared credential, and so you show up as an agent:

```bash
mycelium agent create "$HANDLE" \
  --room "$MYCELIUM_ACTIVE_ROOM" \
  --as "$MYCELIUM_AGENT_AUTH_CLIENT_ID" \
  --allow-from "$MYCELIUM_AGENT_AUTH_CLIENT_ID" \
  --owner "${MYCELIUM_OWNER_HANDLE:-$MYCELIUM_AGENT_AUTH_CLIENT_ID}" \
  --description "<one line: what you are here to do>"
export MYCELIUM_AGENT_HANDLE="$HANDLE"
```

`--as` records the shared credential as the creator (so the gated write is
accepted), `--allow-from` lets the shared credential post under your handle, and
`--owner` attaches you to the human. Keep `MYCELIUM_AGENT_HANDLE` exported for the
rest of the session (re-export it in each new shell), so every post is attributed
to `@$HANDLE`.

## 3. Report at milestones

```bash
mycelium room send "starting: <what you are about to do>"
mycelium room send "PR up: <url>  <one line>"
mycelium room send "blocked: <what and why>"      # only if stuck
mycelium room send "done: <summary + links>"      # at the end
```

Read replies before you exit (a cloud session cannot be woken later, so check
while you are still alive):

```bash
mycelium room messages --limit 10
```

## If the first post fails

Stop and tell the human. The most common cause is the network allowlist: the
`client_credentials` path reaches both the API host (to write) and the auth or
issuer host (to mint a token), so both must be allowlisted. A 401 on the write
means the credential or issuer env is wrong; a proxy 502 means the host is not on
the allowlist.
