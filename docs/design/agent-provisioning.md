# Design: daemon-mediated agent provisioning (UI-driven `agent add` / `rm`)

Status: **proposed** — not implemented. Tracks the follow-up to PR #277.

## Problem

The room UI now shows the full agent loop end-to-end *for agents that already
exist*: an Agents panel lists registered agents, `@`-mention in the chat box
invokes one, and the agent's reply is badged in the event stream. The one
thing the UI cannot do is **register or tear down an agent** — that is still
CLI-only (`mycelium agent add` / `mycelium agent rm`).

Making registration work from the UI is not a thin backend endpoint. It runs
into a hard topology constraint.

## Why a hub endpoint can't do it

Per `docs/guides/hub-and-spoke.md`, a deployment is a **hub** (the FastAPI
backend + DB + channel server — what the frontend talks to) and one or more
**spokes** (CLI + the agent runtime + the dispatcher). Registration's side
effects are *all spoke-local*:

- **`claude_code`** — the cc-daemon resolves manifests from the **spoke**
  filesystem (`~/.mycelium/rooms/<room>/agents/<handle>.md`), and the `cwd`
  that `claude -p` runs in is a **spoke** path. `mycelium agent add` works
  because the CLI writes the hub memory entry *and* mirrors the manifest to
  that local path. A hub-only write is invisible to the daemon.
- **`openclaw`** — `OpenClawIntegration.register()` runs `openclaw agents
  add`, edits the **spoke's** `~/.openclaw/openclaw.json`, and restarts the
  **spoke's** gateway. None of that is reachable from the hub.

Even in a single-machine install the backend usually runs in Docker, so it
cannot touch the host's `~/.mycelium` / `~/.openclaw` either. So
"register from the UI" cannot be a pure hub endpoint under any realistic
topology.

The only component positioned to perform spoke-local provisioning is the
always-running spoke process already subscribed to the hub over SSE: the
**cc-daemon**. Therefore UI-driven provisioning is necessarily
**daemon-mediated**, and **the daemon must be running** for it to work — an
explicit, surfaced precondition, not a silent failure.

## Proposed protocol

```
UI ──POST request──▶ hub records a provisioning *request*
                         (memory key `provisioning/<id>`, status=pending)
                                  │  (hub SSE the spoke already listens on)
                                  ▼
                     spoke cc-daemon picks up the request
                                  │
                                  ▼
            daemon runs the real Integration facet on the spoke:
              register → get_integration(family).register(...)
              teardown → get_integration(family).destroy(..., full=?)
                                  │
                                  ▼
              daemon writes status back (`provisioning/<id>` →
              status=ok|error, detail) + the manifest mirror
                                  │
                                  ▼
                     UI polls/streams the request, shows result
```

Key points:

- **Reuse what PR #277 built.** `Integration.register()` / `destroy()` are
  already the canonical spoke-side side-effect implementations for both
  families. The daemon just needs to *call* them — no new install logic.
- **Request record.** A `provisioning/<id>` memory entry (or a dedicated
  control message type) carries: `op` (`add`|`rm`), `family`, `handle`,
  `room`, family-specific args (`cwd`, `openclaw_agent`, `description`,
  `budget`, `allow_from`, `full` for rm), `requested_by`, `status`,
  `detail`, timestamps. Memory is the natural channel — the daemon and UI
  both already speak it, and it persists for audit.
- **Idempotency / dedupe.** Keyed by `id`; the daemon marks `claimed`
  before acting so a reconnect/replay doesn't double-provision (mirrors the
  existing `seen_message_ids` discipline in `dispatch.py`).
- **Authorization.** Reuse the manifest's `allow_from` notion: only
  configured requesters may provision. The request must be attributable
  (`requested_by`) and the daemon should refuse unknown requesters.
- **`claude_code` vs `openclaw` asymmetry.** The cc-daemon today only
  *dispatches* `claude_code`. For provisioning it must also be able to run
  `OpenClawIntegration.register()` (it has the integration registry
  already), **or** the request is routed to whichever spoke process owns
  that family. Decide: daemon drives both families' provisioning, vs. a
  per-family provisioner. Recommended: daemon drives both (it is the only
  guaranteed-running spoke process; the integration facets are
  family-agnostic to the caller).
- **Failure modes the UI must show.** (a) no daemon running / not
  subscribed to the room → request stays `pending`, UI shows "no
  provisioner — start the cc-daemon"; (b) `register()` raised → `error`
  with the message; (c) timeout → `error` after N seconds. The UI must
  never imply success on a bare hub write.

## Out of scope / open questions

- **Multi-spoke routing.** If two spokes both subscribe to a room, which
  one provisions a `claude_code` agent (whose `cwd` only exists on one)?
  Likely: the request names a target spoke/host, or only spokes that can
  satisfy it claim it. Needs a spoke-identity concept the daemon doesn't
  have yet.
- **Secrets.** `--copy-auth-from` duplicates an OpenClaw auth profile;
  doing that via a UI request means a secret-bearing op crosses the hub.
  Probably keep `--copy-auth-from` CLI-only in v1.
- **Editing** an existing manifest (budget/allow_from) is a smaller subset
  (no runtime side effects for `claude_code`) and could land first as a
  thin slice.
- Relationship to the existing review note that the daemon resolves
  manifests from the local filesystem ("single-machine v0"): a daemon that
  can also *read* manifests from the hub API would reduce the mirror's
  importance and simplify this protocol — worth evaluating together.

## Why this is tracked, not built

It is a real protocol addition spanning hub (request record + status),
cc-daemon (a provisioning capability + claiming + both families), and the
UI (request form + pending/error states). PR #277 deliberately ships the
topology-safe, read-only UI (panel + reply badge) and leaves this as the
next, separately-reviewed unit.
