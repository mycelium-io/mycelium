# Architecture

## Deployment Modes

Mycelium supports two deployment modes. The stack is identical in both;
what differs is *where the agents run* and *how they reach the room*.

### 1. Single-device (default)

Everything (the backend, the SLIM node, agents, and CLI) runs on one
machine, typically a developer's laptop. This is what `mycelium install`
sets up out of the box. No network configuration, no remote services to
point at, no shared infrastructure required.

This is the primary deployment target. Use it when one person (or one
machine) owns the whole agent workflow.

### 2. Hub-and-spoke (small teams)

A second, optional mode for small teams that want to share memory, rooms,
and coordination across machines. One machine runs the SLIM node and
backend (the **hub**); other machines run only the CLI + agents (**spokes**)
as **thin HTTP clients** to the hub API.

| Role  | What runs locally | When to use |
|-------|-------------------|-------------|
| **Hub**   | The SLIM node, the thin FastAPI backend (room moderator), and the UI. | The team's shared coordination server. One per team. |
| **Spoke** | CLI + agents only. Points `server.api_url` at the hub backend. | Each teammate's laptop. Memory and participation go over HTTP `:8000`. |

Stand a hub up and point spokes at the **backend** (required):

```bash
# On the hub: starts the SLIM node, backend, and UI
mycelium hub host
mycelium up

# On each spoke: point at the hub's HTTP API
mycelium config set server.api_url http://<hub-ip>:8000
```

Spokes do not need `MYCELIUM_SLIM_MASTER_SECRET` for the default path. The
SLIM/MLS fabric is hub-side; spokes use `await`/`respond` over HTTP. See
[Security Planes](#security-planes) and the [Hub & Spoke Setup guide](#hub-and-spoke)
for step-by-step instructions.

`mycelium doctor` auto-detects which mode you're in by looking at
`server.api_url` in `~/.mycelium/config.toml`: if it points to
`localhost`/`127.0.0.1`, you're a hub; otherwise a spoke. Override the
auto-detection with:

```bash
mycelium doctor --mode hub     # force hub checks
mycelium doctor --mode spoke   # force spoke checks (skip local-only)
mycelium doctor --mode auto    # default; detect from api_url
```

### Reading a remote room (spoke)

When the backend runs on a remote server (EC2, Raspberry Pi, a hub), a spoke is
a **thin client**: `mycelium memory` and `mycelium room` resolve against the hub
over HTTP, so reads are always fresh and there is **no sync step**: nothing is
mirrored locally to fall out of date.

`room clone` / `mycelium sync` remain only as an explicit **export**: a
point-in-time local snapshot for backup or offline reference, not part of the
normal flow.

```bash
# Optional: export a point-in-time snapshot of a room to local files
mycelium room clone my-project --from http://ec2-host:8000
```

## Stack

Mycelium runs on **one SLIM node** and a thin backend: no database, no
message broker, no vector store.

The hub backend moderates an [AGNTCY SLIM](https://github.com/agntcy) group
channel per room (MLS-encrypted; PSK or SignerJwt on the **SLIM plane**).
Turn-based agents on spokes (and humans by proxy) participate over **HTTP** —
the backend holds server-side presence and serves turns from the durable
transcript. Room state lives on the hub as markdown files; search runs against
a local embedding index. Every spoke reads and writes that state over HTTP.
Coordination messages on the fabric ride SLIM as additive [L9 envelopes](#l9-protocol).

| Layer | Technology | Used for |
|-------|-----------|----------|
| Messaging | one SLIM node (MLS group channels) | per-room encrypted coordination fabric |
| State | markdown files on the hub, under `~/.mycelium/rooms/{room}/` | rooms, memories, plan: the source of truth |
| Search | local ONNX embedding index (JSONL) | ~384-dim semantic recall, no external service |
| Protocol | L9 envelopes over SLIM | `exchange` ticks/replies, `commit:*`, `knowledge` |
| Cognition | the aligner (Pi + NEGMAS) | drives the negotiation (see [aligner](#aligner)) |
| Embeddings | local ONNX model | 384-dim embeddings, no API key |
| LLM | Pi | plan compilation + health probe |
| Backend | FastAPI (room moderator) | membership, transcript, moderation API |
| CLI | Typer + Rich | agent interface |
| Frontend | Next.js + Tailwind | the human-facing app; starts with the stack |

**Participation is built into the CLI.** Any already-awake caller joins a room and
coordinates with two stateless HTTP calls. The backend holds membership via a
presence lease and a durable transcript cursor, so ticks are never missed
between turns:

```bash
# Long-poll until a message is addressed to the handle
mycelium await --room my-project --handle me --json

# Post a reply or opening position
mycelium respond --room my-project --handle me "moving toward 30% …"
```

**An agent is a resident runtime.** A participant is your own live Claude Code or
Cursor session. It just loops the participation calls itself: no wrapper, no
separate process, no shelling out:

```bash
mycelium await --room my-project --handle me     # blocks until you're addressed
# …you reason, in your own context…
mycelium respond --room my-project --handle me "moving toward 30% …"
# …then await again
```

The loop *is* the wake: await → reason → respond → await. The session does the
reasoning **in its own head**; `respond` just posts it. There is no daemon and no
cold-spawn, and agents never speak SLIM or L9 directly.

For a **headless** agent (no interactive session sitting there to hold the loop),
`mycelium await --loop --exec <cmd>` runs the loop for you and hands each turn to
`<cmd>` (turn JSON on stdin); `<cmd>` is your reasoning runtime and calls
`respond`. Point it at a **persistent** runtime (e.g. an Agent-SDK session) so
context accumulates across turns; a throwaway one-shot per turn would just rebuild
the amnesiac cold-spawn this design replaced.

An `@`-mention to a handle with no resident runtime simply waits on the durable
transcript cursor until one awaits. (Waking a handle on demand when nothing is
resident is deferred to a future herdr integration plus per-agent identity.)

**Cognition rides on engines.** First-party [engines](#engines) are registered in
a room and summoned by `@`-mention; each `kind` is a distinct unit of reasoning.
The `aligner` drives negotiation; its brain is a persistent Pi coding-agent
session running a NEGMAS Stacked Alternating Offers mechanism that owns
termination, stopping the instant the agents agree. The `synthesizer` distills
the room's memory into a shared briefing. See [engines](#engines),
[aligner](#aligner), and [episodes](#episodes).

## Adapters

Mycelium integrates with AI coding agents via adapters. The coordination model is
the same regardless of adapter: join, await, respond.

| Adapter | How it connects |
|---------|--------|
| **claude_code** | Skill + resident await/respond loop |
| **cursor** | Workspace rules + the same resident loop |
| **a2a** | A remote Agent2Agent endpoint the hub calls; no local runtime |

### Claude Code

The Mycelium skill installs as a Claude Code skill (`~/.claude/skills/mycelium/SKILL.md`),
invoked via the `/mycelium` slash command for memory and coordination commands.
The adapter is skill-only.

```bash
# The skill is invoked automatically in Claude Code sessions
# or explicitly via the slash command
/mycelium
```

A Claude Code session participates as a resident runtime: it loops `mycelium
await` → reason → `mycelium respond`, picking up each `@handle` mention on its
next turn and answering in its own context. (For a headless, unattended agent,
`mycelium await --loop --exec <cmd>` runs that loop for you; see above.)

### Cursor

Same resident model as Claude Code: a Cursor session loops `await` → reason →
`respond`.

```bash
mycelium adapter add cursor   # installs the workspace rule + AGENTS.md assets
cursor-agent login            # one-time, interactive

# Per agent: --cwd is the session's workspace root (optional)
mycelium agent create design-agent --adapter cursor \
    --cwd ~/repos/my-frontend --room my-project
```

### A2A

An `a2a` agent has no local runtime at all: it is a remote
[Agent2Agent](https://github.com/a2aproject/A2A) endpoint the hub calls on its
behalf. The card is resolved at registration, so a bad URL fails immediately.

```bash
mycelium agent create researcher --adapter a2a \
    --card https://research.example.com --room my-project
```

The same bridge runs inbound: every room is served as an A2A agent, discoverable
at `GET /api/rooms/{room}/.well-known/agent-card.json` (public — discovery is
unauthenticated by the A2A spec) and callable with A2A JSON-RPC at
`POST /api/rooms/{room}/a2a` (gated by the hub's auth when it is enabled).

A bridged agent is a room member for coordination, **not** a member of the
room's MLS group: the backend reads plaintext and calls the remote out-of-band.
See the [A2A bridge](adapters.html#adapter-a2a) for the full boundary.

### Backend API

Any agent that can make HTTP requests can use the REST API directly.
Interactive API docs are available at `http://localhost:8000/docs`
when the backend is running.

## Status providers

Adapters connect **agents** to a room. Status providers connect the **tools your
work already lives in**, so that a [board](#board) row pointing at a pull request
can report whether it's approved, blocked or failing instead of someone copying
that state into Mycelium.

> **Experimental.** The contract, the GitHub provider, and the credential store
> live in the backend (`app/services/status/`), and you can give the hub a
> credential today (below). What is not wired yet is the part that *spends* it:
> no route, no schedule, no field on a board row constructs the runtime, so
> nothing polls a provider on its own. Read this section as what a provider will
> implement, and check the module before writing one.

| Provider | Recognises | Reports |
|----------|------------|---------|
| **github** | `owner/repo#123` and `https://github.com/owner/repo/pull/123` | review decision, checks rollup, draft, merged/closed |

Providers run on the hub only. That is where the credential is, and it means one
cache is shared by everyone in the room rather than each client polling GitHub
for itself. A spoke never holds a service token.

### Giving the hub a credential

Resolving pull requests takes a GitHub token; read-only is enough, plus `repo`
scope for private repositories. A provider **declares** which credential it needs
and how it is presented (a scheme: bearer token, basic auth, a raw key in a
header), and never handles the value. The runtime resolves it and hands back a
transport that already carries it.

You give the hub the value by name, on the machine the backend runs on:

```bash
# The name is the provider's, not yours: GitHub's provider declares GITHUB_TOKEN.
mycelium board credential set GITHUB_TOKEN --stdin < token.txt
mycelium board credential set GITHUB_TOKEN            # or a hidden prompt
mycelium board credential ls                          # names and set/empty, never values
```

The value is read from stdin or a hidden prompt, never the command line, so it
does not land in shell history or `ps` output. It is stored `0600` in
`~/.mycelium/status-credentials.json`, a flat name-to-value file the backend
reads directly (compose already bind-mounts `~/.mycelium` into the container).

Three sources resolve, explicit always beating ambient: a namespaced
`MYCELIUM_STATUS_GITHUB_TOKEN` environment variable overrides everything, then
the stored value, then a bare `GITHUB_TOKEN` environment variable last. The bare
name is a convenience so a container with one injected token and no store file
works, but it sits *below* the store on purpose: a credential name looks like an
ordinary environment variable, so an ambient `GITHUB_TOKEN` set for some
unrelated tool must never silently override one you explicitly stored. To force
an override from the environment, use the namespaced form.

Do not put the value in `config.toml` or hand-edit `~/.mycelium/.env`. Both are
rewritten wholesale (`.env` is regenerated by `mycelium config apply`), so a
token written into either disappears the next time they run, with no error to
explain where it went. The credential store exists precisely to survive that.

A reference whose provider has no credential is refused with the reason, rather
than answered with a blank. A blank on a row reads as *this pull request has no
CI*, which is worse than an honest gap. The runtime refuses it without calling
the provider at all, so a misconfigured one never spends a request discovering
it has no token. The reason distinguishes a name that was never set (*not
configured*) from one set to an empty value (*set but empty*), because an
operator fixes those two differently.

### Teaching Mycelium another tracker

A provider is one small class in `app/services/status/providers/`;
`providers/github.py` is written to be copied. It declares its batching and
freshness, then implements two methods:

```python
class JiraProvider:
    name = "jira"
    base_url = "https://your-org.atlassian.net"   # ctx.http is bound to this host
    auth = Basic("JIRA_EMAIL", "JIRA_TOKEN")  # a scheme, not a value; the runtime resolves both names
    max_batch = 50                  # most references the runtime sends in one call
    ttl = timedelta(minutes=1)      # how long an answer counts as current
    swr = timedelta(minutes=30)     # how long past that it's still shown while refreshing

    def claims(self, text: str) -> list[Ref]:
        """Which references in room text are yours. Mycelium knows no syntax
        of its own: PROJ-14 means a ticket because you said so."""

    async def fetch(self, refs: list[Ref], ctx: Context) -> list[Outcome]:
        """Resolve a batch. One Ok or Err per reference, in any order."""
```

The `auth` line is the whole of what a provider says about credentials. It picks
a scheme and names the value(s) it needs: `Bearer("GITHUB_TOKEN")` for GitHub,
Asana, Sentry or Notion; `Basic("JIRA_EMAIL", "JIRA_TOKEN")` for Jira Cloud, which
takes an identity and a secret rather than one opaque token; `Header("LINEAR_TOKEN")`
for a raw token with no scheme word, or `Header("KEY", header="X-Api-Key")` for a
key under a header of the tracker's own. The runtime resolves the name(s) and
renders the header; a provider never sees the value or writes the encoding.

What you don't write is as important as what you do. `ctx.http` arrives bound to
the declared `base_url`, with the credential, timeout and retry policy already
applied, so a provider is request-and-parse: it names a host and a secret and is
handed neither. Batching, de-duplication, caching, single-flight and rate-limit
backoff belong to the runtime; a provider that reimplements them is doing that
job twice, and worse.

Two rules the runtime enforces:

- **Bulk only.** There is no single-reference fetch to call in a loop. A hundred
  rows resolve in two calls at `max_batch = 50`. A tool that can only answer one
  at a time is still fine: declare `max_batch = 1` and it gets paced.
- **Failure is per reference.** A batch where three links 404 still answers for
  the other forty-seven. A link your token can't see is marked unreachable, not
  reported as green.

Map your tool's vocabulary onto the six states in the
[board's table](#board), being `ok`, `pending`, `blocked`, `failed`, `done` and
`unknown`, and keep your own wording as the label. The state is what the board
sorts and colours by; the label is what the reader recognises.

Your answer will land on a row under a `live` field, never the row's own
`status`. The two vocabularies both contain `blocked` and mean different things
by it, so they are kept in separate fields rather than one shadowing the other.
In the backend the answer is a `Liveness`, named for the same reason.

The host bound is enforced, not merely declared: `ctx.http` refuses any request
to a host other than your `base_url`, so a redirect or a hand-written absolute
URL cannot carry your credential somewhere it was never meant to go.
