# Coordination Transport Pivot — Planning Checkpoint

**Status:** Planning only. No code yet. This doc is a checkpoint to regain shared
context before continuing design. Nothing here is a final decision. Some items are
external facts confirmed from sources; the rest are open questions or current thinking,
noted as such. **[OPEN]** marks something that still needs a call.

**Date:** 2026-08-04

---

## 1. Why this exists

The org is taking the IOC / CFN infrastructure closed-source and redesigning it.
Everything mycelium currently leans on for coordination — the Go CFN (`ioc-cfn-svc`),
the CognitiveEngine, the CFN management plane, the knowledge service — is going away.

Mycelium's job in the new world: **make the L9 protocol usable for a generalist
audience as a shared-group-cognition layer**, riding over an open transport instead
of the CFN. The memory substrate and the coordination *protocol* (join → converge →
plan → work) are the value and must survive; the CFN plumbing underneath does not.

---

## 2. The layering (from AGNTCY / Outshift sources)

Three stacked layers, not competitors — this is external, from AGNTCY / Outshift docs,
not our decision.

```
L9 / SSTP     epistemic payload — belief state, episode URN, causal parents,
              subkinds (exchange / commit:converged / abort). "Layer 9."
              We already build this. It stays.
  rides INSIDE ↓
A2A           Google's agent-message wrapper — Agent Cards, tasks, JSON-RPC.
              "Layer 8." Defines WHAT agents say. Now under the Linux Foundation.
  transported OVER ↓
SLIM          AGNTCY secure messaging fabric — gRPC/HTTP2, pub-sub,
              MLS-encrypted multicast GROUPS. Defines HOW bytes move.
              Formerly AGP / Agent Gateway Protocol.
  on ↓
HTTP/2 · TLS · gRPC
```

- Ordering is **A2A over SLIM**, never the reverse. L9 is the payload carried inside. (This
  is the general AGNTCY layering. **Our actual design skips A2A for the room bus** — L9 rides
  straight over SLIM group sessions; see §8/§11. A2A stays optional, for later point-to-point
  task invocation across frameworks.)
- The L9 reference implementation already treats transport as a **swappable interface**
  (`AgentBus`). The CFN was just one binding (`A2AAgentBus`, POST-to-fabric). So dropping
  the CFN = **swapping the transport binding**, not tearing down the architecture.
- A **room maps to a SLIM multicast group** (MLS-encrypted) = the native
  shared-group-cognition primitive.
- Schema gotcha to reconcile later: public SSTP uses `commit:rejected` for a failed
  negotiation; the CFN table we adopted uses `commit:abort`.

---

## 3. Teardown blast radius (from a repo sweep)

The teardown is **vertical, not horizontal** — CFN sits *on top of* the memory/room
fundamentals, not woven through them.

**Removed:**
- `coordination.py` (~82KB orchestrator), all `cfn_*.py` services, `l9_cfn.py`
- Generated `ioc_cfn_svc_api_client/` (2.1MB) + `cfn_swagger.json` + `gen-cfn-client.sh`
- CFN routes: knowledge ingest, `cfn_proxy`, coordination, coordination_sessions
- CLI commands: `session`, `negotiate`, `cfn`
- The entire `cfn` Docker profile (mgmt-plane, knowledge-memory-svc, ioc-cfn-svc,
  cognition-engine) and all `CFN_*` config/env

**Survives untouched:**
- Memory set/get/ls/search (filesystem + pgvector), rooms-as-folders, messages,
  presence, SSE streaming, plan storage + the LLM `plan_compiler`
- **L9 splits clean:** `l9.py`, `l9_episode.py` (MPC/GAR/SCR metrics), `l9_models.py`
  are pure payload/metrics logic with **zero CFN calls** — they stay. Only `l9_cfn.py`
  (the poster to the fabric) is coupled and goes.

### Memory can go markdown-first

Files were always the source of truth (rooms are folders, memories are markdown —
mycelium's original idea); AgensGraph was only ever the *index* bolted on for CFN-era
search. With the knowledge service and knowledge-graph gone, the store collapses back to
markdown. The one piece that actually used the DB is `memory search` (pgvector semantic
search).

- `[OPEN]` **Where does search live now** — a lightweight local vector index over the
  markdown, a slimmed-down pgvector, or drop semantic search for something simpler.
  Everything else in memory is just reading/writing files.
- `[OPEN]` **Bigger thread:** once coordination moves to SLIM *and* the knowledge graph is
  gone, what still needs the Postgres DB at all? Presence, messages, subscriptions, and
  LISTEN/NOTIFY-driven SSE are the remaining users. Worth its own look later.

---

## 4. Where convergence goes — current direction

This is the direction from Julia's boss, not a locked decision. The idea: don't rebuild
the CFN's alignment scoring as a backend service. Instead —

> the semantic-negotiation / convergence step becomes an **agent within the MAS** — a
> participant mycelium spawns and curates, sitting in the room like any other agent, on
> the same SLIM group, emitting its verdict as its own L9 message.

What's appealing about it:
- Convergence used to live in another team's service at their velocity. As an agent we
  author, we'd own the consensus definition ourselves.
- It reuses machinery we already have. Mycelium's `agent` command already spawns agents
  into disparate runtimes (openclaw / claude_code / cursor). That existed for onboarding
  — a user has 1–2 agents but shared cognition needs 3+ to be legible. The same mechanism
  could also seed the aligner agent.
- It fits the existing seam. `plan_compiler` was built as a consumer stage, not a CE step.
  If the aligner emits `commit:converged`, the backend could watch for it and fire the
  compiler — same seam, producer moved from CFN into an agent. `l9_episode.py`'s local
  MPC/GAR/SCR metrics could become the aligner's tooling.

One thing to be aware of: this cuts against the current core design decision
*"CognitiveEngine mediates — agents never talk to each other directly."* In this
direction, agents talk peer-to-peer in a SLIM group and the aligner participates as a
peer, not a broker. That's a real shift from how mycelium works today, not a small edit.

---

## 5. How agents communicate, and the SLIM question [OPEN]

An agent has two ways to communicate in mycelium:

1. **Via the CLI** — the agent runs mycelium commands to post into a specific room.
2. **Natively** — the agent just talks in its own interface, without running any mycelium
   commands. Today this is what the OpenClaw channel does: the agent speaks normally and it
   surfaces in the room.

The open question is whether the **native** mode can be carried over SLIM.

- The CLI mode is ours end to end — it's our code, so it can put messages on SLIM however
  we build it. That part isn't in question.
- The native mode is the unknown. For an agent to just talk and have that travel over SLIM,
  something has to sit in the agent's own interface, capture what it says, carry it onto the
  SLIM group, and bring group messages back in — the way the OpenClaw channel plugin does
  today against the current backend. Whether that pattern can be rebuilt over SLIM, and
  whether it generalizes past OpenClaw, is not worked out.

Nothing here is decided.

### Related, not yet settled: memory vs coordination traffic
One thing to figure out alongside this: memory operations (set/get/ls/search) are just
fs + pgvector, not coordination, so they may not need SLIM at all — they could stay plain
HTTP to the backend, with only the coordination/group traffic going over SLIM. Noting it
as a likely split to examine, not a conclusion.

---

## 5.5 The wake-up problem — the actually-hard part [OPEN]

Independent of transport, the hardest part of any of this is mundane: **when it's an
agent's turn to act, how does an external system wake it up?** SLIM does not solve this.
**SLIM is delivery, not attention** — it moves bytes to a subscriber; it doesn't make the
agent notice and act. A message on a SLIM group is as inert as a message in any inbox until
the harness does something with it.

The real variable is the **wake model of each harness**, which splits agents into two camps:

- **Push-wakeable** (OpenClaw, chat apps): long-lived harness with a native "you were
  tagged → wake" primitive. Async wake is basically free — a connector turns an inbound
  group message into a tag and the agent wakes.
- **Poll / episodic** (Claude Code; Cursor and Hermes TBD): the agent is an episodic
  process, nothing external can push it into attention, it has to *choose* to check an
  inbox — set up a monitor, block, act on a flag — and making that *feel right* (no
  busy-wait, no stall, interleaves with real work) is the actual engineering. SLIM changes
  none of it.

Concretely for Claude Code: **`mycelium await` already *is* the monitor** — the agent runs
it, it blocks until a tick, returns, the agent acts, then has to choose to await again.
Under SLIM that's unchanged in spirit; `await` just blocks on a SLIM subscription instead
of SSE. The transport swap doesn't touch the wake UX.

**Correction (verified in SLIM source):** SLIM does **not** make the inbox durable. Its
"persistence" only restores an agent's *own* session/MLS state across a restart — it is
**not** store-and-forward. An agent that's asleep when a message is broadcast **never
receives it**; rejoin only re-keys the group, it does not replay. There is no mailbox or
backlog. So SLIM can't make the inbox self-opening *or* durable — **the durable inbox is
something mycelium has to build** (an always-on per-room member that persists the
transcript and re-serves what a waking agent missed — see §11).

Two consequences:
- The connector has **two jobs, and only the first is transport:** (1) get messages on/off
  SLIM (easy), and (2) bridge SLIM delivery to the harness's wake model (hard, entirely
  per-harness).
- This is a **different axis from §5's native-vs-CLI.** Even a perfectly native connector
  can't manufacture a wake primitive the harness lacks — for Claude Code, native
  participation is still bounded by a poll. It's why CC coordination was always painful and
  won't get easier just by moving to SLIM.

Implication for the adapter sketches (next): **wake model is the first question to ask of
each adapter**, not an afterthought — it's the part most likely to be hard.

---

## 6. A SLIM node is required (transport fact)

SLIM has no brokerless mode. You have to run a SLIM data-plane node/gateway (default
`:46357`) as the fabric; all bindings are clients that `connectAsync` to it. In compose
terms, that means the 4-service `cfn` profile would be replaced by at least one SLIM node
service. It's a transport node, not a cognition service — lighter than what it replaces.

---

## 7. Implementation notes per agent family [OPEN]

These are open, and they depend on the §5 native-vs-CLI question.

**CLI family (claude_code / cursor / shell).** The CLI/daemon is already the thing that
talks to mycelium. If it's the path, it would speak SLIM instead of hitting the
coordination backend, and the current `mycelium await` / SSE path is what changes. Whether
we also want a native (non-CLI) path for these runtimes is part of the §5 open question,
not settled here.

**OpenClaw.** The native-channel behavior is that coordination is implicit — the agent
just chats and the plugin makes it appear in the room. The plugin is TypeScript/Node, so a
relevant question was whether SLIM can be spoken from JS/TS at all. What the research
found:

- A native JS/TS SLIM client exists and is published: `@agntcy/slim-bindings@1.4.1` (native
  UniFFI addon, prebuilt macOS/Linux/Windows x64+arm64, ESM, Node ≥18, supports
  group/multicast). So a TS plugin speaking SLIM directly is possible.
- A mature A2A JS SDK exists too: `@a2a-js/sdk@1.0.1`.
- The A2A-over-SLIM JS transport (`@agntcy/slim-a2a@0.1.0`) is very green (single release,
  weeks old). The Python twin (`slim-a2a-python`, `v0.6.1`) is further along.

Rough options that fall out of that, none chosen:
1. Plugin speaks SLIM natively in TS (`@agntcy/slim-bindings`) — keeps the native-chat
   behavior, no daemon dependency, but leans on young JS packages (more so if it needs the
   `0.1.0` A2A-over-SLIM layer).
2. Plugin shells out to a Python CLI/daemon for the SLIM hop — one SLIM implementation,
   more-mature A2A transport, but adds a local-daemon dependency.
3. Make OpenClaw coordination CLI-explicit like the others — simplest, but loses the
   "agent doesn't know it's in mycelium" property the native channel was built for.

Which of these makes sense is tied up with the §5 question and with how much A2A we
actually need (§8).

---

## 8. Open decisions

- **[OPEN] OpenClaw edge:** native TS SLIM (1) vs Python sidecar (2). See §7.
- **[OPEN, leaning "minimal"] How much A2A do we actually need?** Research finding: for a
  symmetric "everyone hears everyone" room, **raw SLIM group sessions fit better than A2A
  multicast** (which is request/response fan-out, not a broadcast bus). So the room bus can
  be L9 envelopes straight over SLIM group sessions — no A2A, and no dependency on the
  immature `@agntcy/slim-a2a@0.1.0`. A2A only earns a place if we later want point-to-point
  capability/task invocation + Agent-Card discovery across frameworks. See §11.
- **[RESOLVED in §15] The always-on room member = the backend.** Because SLIM has no durable
  inbox (§5.5 correction), *something always-on per room* must persist the transcript and
  re-serve missed messages, be the SLIM moderator (membership), and trigger plan-compile on
  `commit:converged`. §15 settles this: it's the **backend** (cheap, always-on), *not* the
  aligner (which is summoned and ephemeral — and can't be the moderator precisely because a
  moderator must be always-on). This also resolves "does the backend join the group?" → **yes,
  by construction**, which in turn satisfies the §9.5 inspector's on-the-wire dependency.
- **[OPEN] Aligner (cognition engine) spec:** what runtime does it run in, and its consensus
  logic (it runs L9's SIEP/SAB using the deterministic MPC/GAR/SCR library over the
  transcript — see the three-way split in §15). Summoned, not always-on.
- **[RESOLVED by going SLIM-native] `abort` vs `rejected`.** `abort` was the Go CFN's
  runtime table; off-CFN we're back in spec territory where the L9-native failure subkind is
  **`rejected`**. Going SLIM-native picks `rejected` — just needs documenting.

---

## 9.5 Protocol inspector in the UI [PROPOSED]

Make the protocol **legible** in the mycelium interface: expand a room message and see
the **L9 envelope** (subkind, episode URN, causal parents), the **A2A task** it rode in,
and the **SLIM group** it traversed.

Why this belongs to us specifically: in the funnel **AOP (art of the possible) → mycelium
→ enterprise repo**, mycelium is the one stop where a human actually *watches the protocol
work*. If L9 is the star of the show, mycelium is the theater. A payload inspector turns
invisible plumbing into a visible demonstration of IOC — and differentiates us from "just
another multi-agent chat."

Dependency: this needs mycelium to be on the wire — the backend joining the SLIM group as
observer/persister (see §8) and streaming parsed payloads to the frontend. It would reuse
the same tap as the plan-compile trigger.

---

## 9. Not yet designed (next passes)

- A proper architecture *diagram*. §10 sketches the target-state shape in prose; a real
  diagram (services, processes, ports) still to come.
- Migration/removal plan (note: when this reaches execution, scope goes in one PR — no
  phased splits).
- Proof-of-value: **settled as the hero demo in §13** — cross-person, cross-machine agent
  collaboration with consent-based wake. (Not the "distributed personal-agent memory" pitch.)

---

## 10. Target-state skeleton [SKETCH]

A first pass at the shape. Not a decision — it's the picture everything else (adapters,
CLI, room system) hangs off of, with the real unknowns marked `[OPEN]` inline.

> **Superseded specifics (this was an early pass):** the aligner is **summoned, not
> always-present** (§15); the **backend is the always-on moderator + persister** and is on
> the group **by construction** — not a "maybe observer" (§15); and memory is **markdown +
> JSONL, no pgvector/DB** (§16). The narrative below still holds; read those three as fixed
> where the text below hedges them.

### The cast

- **Participant agents** — the user's agents across frameworks (OpenClaw, Claude Code,
  Cursor, Hermes, …). Each reaches the coordination fabric through a **connector** (its
  edge into SLIM). What that connector is per family is §7, and whether it's native or CLI
  is §5 — both `[OPEN]`.
- **Aligner agent** (name is a placeholder) — mycelium-spawned, sits in the room like any
  other participant, does the convergence step, emits the verdict as its own L9 message.
  Current direction, §4.
- **SLIM node** — the transport fabric (a process, default `:46357`). Carries the group
  traffic. §6.
- **Mycelium backend** — memory substrate + room/group provisioning + `plan_compiler`.
  Possibly also a **group observer/persister** (for the plan-compile trigger and the
  inspector) — `[OPEN]`, §8.
- **Memory store** — markdown files + a local JSONL search index (no pgvector/DB — §16).
- **Frontend** — the room UI; possibly the protocol inspector (§9.5).

### What a "room" becomes

Today a room is: a persistent identity + a folder (memory) + a DB record. That part
stays. What's added is a **live coordination fabric** — a SLIM group — that the room's
participants talk on when they're actually coordinating.

- `[OPEN]` **Group lifecycle.** Is the SLIM group **persistent per-room** (always up,
  participants come and go) or **ephemeral per-negotiation** (spun up for a coordination
  session, torn down after)? Today rooms are persistent and *sessions* are the ephemeral
  negotiation spawns — so a natural mapping is "room = durable identity, a negotiation =
  a SLIM group/channel instance," but that's not worked out.
- `[OPEN]` **Who provisions the group and when** — presumably the backend at room/session
  creation, but TBD.

### One cycle, end to end

Tracing `join → exchange → converge → plan → work`, noting transport (SLIM vs HTTP) and
the L9 kind of each message. Steps that are unknown are flagged.

```
                       ┌──────────────── SLIM group (the room's coordination fabric) ─────────────┐
   participant A ──connector──▶│                                                                  │
   participant B ──connector──▶│   exchange · exchange · … · commit:converged                     │
   aligner (summoned) ───────▶│  (joins only when invoked — §15)                                 │
   backend (moderator+persister)▶│  always on the group by construction — §15                     │
                       └──────────────────────────────────────────────────────────────────────────┘
                                          │ commit:converged seen here
                                          ▼
                       backend plan_compiler  ──writes──▶  plan/tasks.md  (memory, files)
                                          │
   participant A ◀───── reads plan (HTTP memory) ─────┘   then does the work
```

1. **Join.** A participant's connector joins the room's SLIM group. The aligner joins
   too. `[OPEN]` how the join happens per family (native vs CLI, §5) and whether the
   backend joins (§8).
2. **Exchange.** Participants post their positions as L9 `exchange` messages onto the
   group. This is peer-to-peer on SLIM — not brokered through the backend the way it is
   today. (This is the inversion noted in §4.)
3. **Converge.** The aligner reads the exchange traffic, runs its consensus logic
   (`[OPEN]` — LLM judge vs MPC/GAR/SCR thresholds vs hybrid, §8), and emits the verdict
   as an L9 `commit:converged` (or `abort`) message onto the group.
4. **Plan.** Something watching the group sees `commit:converged` and triggers the
   backend's `plan_compiler`, which materializes `plan/tasks.md` into the room's memory —
   the same consumer seam as today, just fed from the group instead of from CFN. `[OPEN]`
   what does the watching: the backend-as-observer, or the aligner calling the backend,
   or the aligner compiling the plan itself.
5. **Work.** Participants pick up the plan. Plan/memory reads stay **plain HTTP to the
   backend** — not SLIM. Only the coordination traffic (steps 2–3) rides the group.

### What stays the same

- **Memory** — set/get/ls/search stay local reads/writes; markdown files + a local JSONL
  index (no pgvector/DB — §16).
- **L9 envelope shapes** — `l9.py`, `l9_episode.py`, `l9_models.py`. The `exchange` and
  `commit` payloads are the same shapes; what changes is the transport they ride and who
  emits the `commit` (the aligner, not CFN).
- **The plan-compile seam** — `plan_compiler` stays a consumer stage, triggered by a
  `commit:converged` it observes across a seam.

### The open questions this shape surfaces (pointers, all covered above)

- Native vs CLI per family (§5) · how much A2A (§8) · does the backend join the group (§8)
  · group lifecycle: per-room vs per-negotiation (this section) · aligner consensus logic
  and count (§8) · who triggers plan-compile (this section).

---

## 11. SLIM-native architecture — first sketch [SKETCH]

Grounded in reading the actual SLIM / slim-bindings / slim-a2a / ioc-protocols-models
source (local clones under `~/Documents/GitHub/_slim-research/`). Not a decision — a shape,
with unknowns marked. The framing: **SLIM-native, not drop-in.** Today mycelium's backend
is the hub — rooms, presence, messages, SSE, and coordination all flow through FastAPI +
Postgres. SLIM-native inverts that: **SLIM becomes the nervous system**, and the backend
stops being the message hub.

### What you actually run

- **Minimum: one stateless `slim` node** — a single ~100m-CPU / 128Mi container on port
  46357; `slimctl slim start` in dev; no DB, no control plane. Agents embed a SLIM binding
  and connect as authenticated data-plane clients. **This replaces the whole 4-service CFN
  profile with one lightweight container.**
- **Federation is opt-in and later:** a `slim-control-plane` + SPIRE (mTLS identity) +
  optional `channel-manager` only when you need multi-host / multi-cluster / cross-org
  routing. Nodes peer via static config or k8s discovery (intra-domain) and control-plane
  links (inter-domain).
- **All self-hosted — there is no SaaS SLIM.** So mycelium's install bundles the node.

### What gets installed (the running processes)

The confusion worth clearing up: **SLIM-the-protocol is a spec; SLIM-the-running-code is a
single Rust binary, `slim`** — the data-plane node. That node *is* "the hub": every agent
connects to it and it routes/fans out messages by name. It runs **no LLM, stores no
messages, and knows nothing about L9** — a dumb, fast, secure pipe. All intelligence lives
in mycelium code connected to it.

**Install change:** today `mycelium install` / `up` runs the `cfn` compose profile — 4
services (mgmt-plane, knowledge-memory-svc, ioc-cfn-svc, cognition-engine). SLIM-native
**swaps that whole profile for one `slim` service**. Install gets *lighter*.

Minimal hub config + run:
```yaml
# slim-config.yaml
services:
  slim/0:
    node_id: mycelium-slim
    dataplane:
      servers:
        - endpoint: "0.0.0.0:46357"
          tls: { insecure: true }    # local; SPIRE/mTLS in prod
      clients: []                     # no peers = single standalone hub
```
```
docker run -p 46357:46357 ghcr.io/agntcy/slim:latest /slim --config /slim-config.yaml
# dev shortcut, no config: `slimctl slim start`  → node on :46357
```

The full set of processes in a SLIM-native local install:

| Process | Role | Source | Port | Stateful? |
|---|---|---|---|---|
| **`slim` node** | the hub — routes/fans out messages by name | `ghcr.io/agntcy/slim` image (new) | 46357 | no |
| **mycelium backend** | provisioning, identity/naming, always-on persister, aligner spawner, memory | existing (slims down) | 8000 | via db/files |
| **db** | ~~memory index~~ | **dropped — see §16** (replaced by a local JSONL index) | — | — |
| **agent connectors + aligner** | *connect to* the hub as clients; embed the SLIM binding | per-host daemon or in-adapter | — | no |

`[OPEN]` **Where the hub lives for the cross-machine case** — the first real fork in the
distributed story (and the one closest to the "my agent talks to your agent" pitch). With a
single node, everyone connects to one hub (`localhost:46357`, or one shared host). Across
machines/orgs you either (a) point both sides at **one shared hub** (bundled-per-user vs a
mycelium-hosted shared node — an operational + trust decision), or (b) run **a hub per side
and peer them into a mesh** (control-plane + SPIRE appear here). None of this is needed to
start — a single node covers local and single-host.

### Naming & identity — a new mycelium responsibility

- SLIM addresses by a hierarchical **`org / namespace / app` name**, routed by the node
  (not DNS/IP). Proposed mapping: **org = workspace/tenant, namespace = room, app = agent**;
  a room's channel is a Name whose last segment is the channel/topic.
- **Mycelium becomes the identity/naming authority:** it mints per-agent identities and
  secrets. Dev = shared-secret (≥32 chars, also seeds MLS); production = JWT or SPIRE-issued
  SVID mTLS. `[OPEN]` which tier we target first.

### Room = SLIM group channel

- Creating a room provisions a **group (multicast) channel**. The **backend is the
  moderator** (creator; the only one who invites/removes members) — it must be, because the
  moderator has to be always-on, and per §15 the backend is the cheap always-on layer while
  the aligner is summoned. Other agents `subscribe` their name and get invited in.
- **Any member broadcasts to all** → the room bus. **Presence is built in** (online/offline
  via decentralized heartbeats). **MLS gives optional end-to-end group encryption with no
  key server** (moderator-driven, forward secrecy on join/leave).
- Receiving is a **blocking async pull** (`get_message` loop) — this *is* the connector's
  wake monitor from §5.5.

### The message path

- **L9 envelopes broadcast straight over the SLIM group session.** Per the A2A finding
  (§8), raw group sessions beat A2A multicast for a symmetric room, so the room bus needs no
  A2A wrapper.
- The L9 side plugs in at a clean seam: L9 exposes a `NetworkHandle` interface
  (`send(header)` + a per-agent handler registry). A **`SlimAgentBus(NetworkHandle)`**
  publishes headers over the group and dispatches inbound to local handlers. Mycelium
  already builds L9 envelopes, so it sits exactly at `send(header)`; the episode logic is
  transport-agnostic.

### What SLIM gives free vs. what mycelium must still build

**Free from SLIM:** the message bus, fan-out, presence, group E2E encryption, at-least-once
delivery *to online members*, cheap rejoin after restart.

**Mycelium must still build:**
- **The durable inbox.** SLIM drops messages sent while an agent is asleep (§5.5
  correction). → an **always-on per-room member** persists the transcript and re-serves what
  a waking agent missed.
- **Causal ordering by L9 `message.parents`.** SLIM orders by its own sequence, not the L9
  causal DAG — the app enforces parent-before-child.
- **Episode ↔ channel lifecycle.** L9 requires stable membership for an episode and says a
  mid-episode join/leave aborts the episode; SLIM allows live membership changes — so the
  app maps SLIM membership events onto episode boundaries.
- **Identity / naming** (above) and **per-harness wake-up** (§5.5) — unchanged hard parts.

### The always-on room member (load-bearing)

Because of the no-durable-inbox fact, each room needs an always-on presence that:
persists the full transcript → **markdown memory**; re-emits missed messages to waking
agents (the durable inbox); watches for `commit:converged` → triggers `plan_compiler`; and
feeds the **protocol inspector** (§9.5). **§15 settles who plays it: the backend** (cheap,
always-on) — *not* the aligner, which is summoned and ephemeral. When the aligner is invoked
to judge, the backend hands it the transcript it needs (MPC/GAR/SCR are history-derived and
reconstructable from the wire log the backend keeps).

### The backend's new role

Not the coordination engine (that's the aligner, on the group) and not the message broker
(that's SLIM). It becomes: **fabric provisioner** (channels, identities, names) +
**always-on persister / durable inbox** + **markdown memory + search** + **spawner/curator
of agents including the aligner** + **protocol-inspector feed**. The Postgres surface
(messages, subscriptions, LISTEN/NOTIFY-driven SSE) falls away entirely once the bus and
presence live in SLIM — **§16 decides the DB is dropped**, backend collapses to a thin local
process over markdown + JSONL.

### Open questions this sketch surfaces (pointers)

Identity tier (shared-secret vs JWT/SPIRE) · ~~who is the always-on persister~~ (resolved:
the backend, §15) · where causal-ordering + episode-abort enforcement lives · ~~how much of
the Postgres DB survives~~ (resolved: none — dropped, §16) · aligner runtime + spec (§8) ·
native-vs-CLI per family (§5) still applies to how each agent's connector attaches to the
group.

---

## 12. Where the human sits — and how @-mention maps [SKETCH]

The rest of the doc is agent-to-agent, but mycelium's actual product is **multi-user
chat**: humans and agents in a room together. Current model — the human interacts in the
mycelium room (the channel), **tagging agents with `@`**; agents can also `@`-invoke other
agents. That has to survive.

### Does a SLIM payload need a "to"? No (for a room)

- **Group/channel message: no explicit recipient.** `publish` fans out to *every current
  member* of the channel — like posting in a Slack channel. (An optional `publish_to`
  targets a reply back to one member via the message context; the default is broadcast.)
- **Point-to-point session: yes** — bound to a destination `org/ns/app` Name; a true 1:1
  pipe if we ever want private agent-to-agent DMs.
- The address unit is the **Name**; a channel is a Name members subscribe to.

### So `@`-mention is an application concept, not a transport address

Three levels stack:
1. **SLIM transport** — broadcast to the channel. Everyone hears everyone.
2. **L9 envelope** — `participants.actors[]` marks *sender / recipient / observer*. The real
   semantic "to."
3. **Human/UX** — `@agent-x` compiles into L9 recipients (agent-x = recipient, others =
   observers).

This is exactly Slack semantics (everyone sees it; the mention pings who should act), so the
multi-user-chat model is **native to SLIM groups** — no fighting the grain.

### Where the human connects

The human does **not** run a SLIM connector. The **backend/UI represents them on the
fabric** — publishing their messages (with `@`-mentions) into the channel, and showing them
the room via the persisted transcript (the same feed as the inspector, §9.5). `[OPEN]`
whether the human gets their *own* SLIM identity or is simply spoken-for by the backend.

### Two flavors of `@` (they interlock with earlier threads)

- **`@`-mention an agent already in the room → a wake.** The always-on persister (§11) sees
  the mention, wakes that agent, and re-serves what it missed while asleep. This is where
  `@`-mention, the wake-up problem (§5.5), and the durable inbox turn out to be **one
  mechanism**. (Note: SLIM only broadcasts to *connected* members, so a mentioned sleeping
  agent doesn't even receive the message until the persister re-serves it — which is exactly
  why the persister must exist.)
- **`@`-invoke an agent not in the room → a membership change.** The moderator invites it to
  the channel and spawns it.

### Collision to flag

`@`-invoking a *new* agent mid-negotiation hits L9's "membership stable per episode" rule
(a mid-episode join aborts/restarts the episode, §11). So `@`-invite during an active
convergence needs a policy — **queue it until the episode closes, or accept a restart.**
`[OPEN]`

---

## 13. Hero demo / proof-of-value [SKETCH]

### The vertical

**Multiplayer, multi-agent, multi-human, across machines.** Two people's agents, on two
different machines, coordinating on shared work — with the humans supervising and steering.

This is deliberately **not** the "distributed personal-agent memory" pitch (the "my agent
knows I like Italian food so it books lunch" scenario). That one fails a simple test.

### The test that picks the hero (and kills the weak one)

**Does the scenario actually need what we're building?** Auto-booking a restaurant is a
single agent doing a calendar action — no second agent, no negotiation, no cross-machine
anything. It's a party trick dressed as coordination. Cross-person agent collaboration on
shared work genuinely *requires* a shared addressable space across machines, identity +
consent, a convergence protocol, and shared persistence — i.e. exactly SLIM + L9 +
mycelium, and exactly what a single-machine agent framework can't provide.

### The differentiator: consent-to-be-woken

The "someone's agent wants to reach your agent — accept?" moment is not a wart, it's **the**
feature. Controlling when your agent gets pulled into someone else's work is the trust
primitive that makes cross-person coordination acceptable at all. It should feel like
*accepting a call*, not like a background daemon poking you. **That UX is the product
surface** and deserves real design.

### The flow

Julia (machine A, backend) and Sam (machine B, frontend), each with a local coding agent +
mycelium, need to agree on an auth API contract — the "you build your half, I build mine,
and they have to match" problem that today means humans copy-pasting between two agent
sessions.

1. **Join machines.** Julia runs `mycelium connect sam`. Under the hood SLIM joins the two
   machines (shared hub, or their two `slim` nodes peer into a mesh — the §11 hub-location
   fork, now motivated). A cross-machine room (one SLIM channel) spans both laptops.
2. **Consent-based invite.** Julia `@`-invites Sam's agent on task "auth contract." SLIM
   delivers the invite to machine B; Sam's side surfaces **"Julia's agent wants to
   coordinate on 'auth contract' — accept?"** Sam accepts → his agent's connector joins the
   channel and wakes.
3. **Kickoff.** Julia posts: "@both — settle the `/auth/token` request+response shape."
   Broadcast over SLIM to both agents; each runs locally but sees the room.
4. **Converge.** The two agents exchange proposals as L9 `exchange` messages over the group.
   The aligner (summoned when convergence is needed — §15) runs SIEP convergence and emits
   `commit:converged` with the agreed contract.
5. **Plan.** `plan_compiler` materializes a shared plan → Julia's tasks (backend) + Sam's
   tasks (frontend), persisted to markdown memory, shared to both.
6. **Work.** Each agent implements *its* side locally; the humans supervise and `@`-steer.
7. **The wake payoff (later).** Julia's agent finishes and `@`-mentions Sam's agent with a
   change. Sam's agent is asleep — the always-on persister wakes it (per Sam's consent
   policy) and re-serves the message it slept through.

### Why it's the right hero

- **It preserves the protocol.** Steps 2–6 are `join → converge → plan → work` — the thing
  we're not allowed to lose — just stretched across two machines via SLIM.
- **It doubles as the AOP showcase.** The protocol inspector (§9.5) showing L9 envelopes
  physically crossing from one laptop to another is a compelling "watch the protocol work"
  visual — which is exactly the AOP → mycelium → enterprise funnel's job for mycelium.

### Honest caveats

- **The value is real but narrow** — it lands for teams already leaning hard on coding/work
  agents. A fine wedge, not a mass market. Better an honest wedge than a fake mass market.
- **The consent-wake UX is make-or-break.** Clunky → it feels like the janky daemon. Like
  accepting a call → it feels like magic.

---

## 14. Shared memory & sync [SKETCH]

### How it works today (ground truth — corrected from code)

**Not git.** (CLAUDE.md's "Git for sharing" line is stale and doesn't match the code — two
"git" mentions in `commands/memory.py` are dead comments. Flag to fix.)

- **Central backend is canonical** — Postgres rows + markdown files on the *server*. Each
  client keeps a local `.mycelium/` mirror.
- **Write:** `memory set` → `POST /api/rooms/{room}/memory` (backend writes file + DB row +
  embedding + Postgres NOTIFY) → CLI drops a local copy.
- **Read:** `memory get`/`ls` read **local files only** — no network.
- **Sync down:** `mycelium sync` = an **HTTP GET pull** (ETag-gated) that writes files
  locally + reindexes. **Pull-only** — no push-up command; re-`set` is the only way up.
- **Real-time:** the SSE `memory_changed` event is a **notify-only ping** (key/version/who),
  **no content** — you still `sync` to pull the bytes.

### The SLIM-native upgrade

The insight that knowledge writes are L9 + SLIM turns today's *notify-then-pull* into
*push-with-content*:

- An episode's L9 **`knowledge` phase** emits `knowledge` messages onto the room channel,
  and those **carry the content**.
- Each participant's connector **writes the markdown locally + reindexes on arrival** — no
  manual `sync`.
- Cross-machine, this replaces "one shared central backend everyone pulls from" with
  **per-machine local stores kept in sync by the L9 knowledge stream** over SLIM.
- Refines the earlier "memory stays HTTP" note: **local memory CRUD stays HTTP to the
  *local* backend; cross-machine propagation rides L9-over-SLIM.**

"Sync down," concretely: a knowledge L9 message lands on the channel → the connector writes
`rooms/{room}/{key}.md` + reindexes. Push, content-carrying, real-time. No commit surface,
no git.

**Conflict policy — decided (Julia): last-write-wins, no merge handler.** Default is
last-write-wins (order by version / timestamp). When a genuine conflict is detected — a write
lands on a stale base (someone already wrote that key) — **don't merge: fail the write with
details** (current content + `updated_by` + `updated_at`) and move on. Explicitly *not*
building a merge-conflict handler. This is nearly free: memory already carries a `version`
that bumps on upsert, so last-write-wins + stale-base rejection reuses what exists.
`[OPEN]` still: whether any central backend remains in the cross-machine case, or it's purely
peer stores.

### Why this over git (honest)

- mycelium **is not a VCS and shouldn't pretend to be.** For versioning, merge, and offline
  history, git wins — and today's pull-sync is *simpler* than git, not better.
- What git **categorically cannot do:** stream a live delta into a running agent's working
  set mid-task. Git is manual / pull / offline. mycelium memory (over SLIM/L9) is push /
  live / agent-integrated — it *is* the coordination channel's knowledge phase.
- So the pitch is **not "better git"** — it's "the live, structured, agent-readable brain
  that coordination writes into and keeps synced across devices in real time." Value coupled
  to the coordination story (§13), not standalone storage.

### The one seam

**L9's `knowledge` phase is the write path into memory.** Converged cognition → `knowledge`
messages → markdown (local) → synced live over SLIM. One seam joins the protocol and the
store — which is why memory finally becomes a first-class part of the coordination story
rather than a side system.

---

## 15. How the cognition engines work [SKETCH — expands §4]

### Three things were bundled under one name — separate them

The "aligner / cognition engine" was doing three unrelated jobs. Split them and it gets
legible:

1. **Room infrastructure** — membership + the durable transcript (persister/inbox). Not
   cognition; plumbing. Always-on, cheap → **the backend**.
2. **Protocol machinery** — grounding checks, metric computation (MPC/GAR/SCR), TFP
   set-cover. Deterministic math over the transcript → **a library**, not an agent.
3. **Cognitive judgment** — "is this converged? what's the agreement? does this position
   win?" The genuinely intelligent part → **the cognition engine** (an LLM agent), using #2
   as tooling over a transcript #1 maintains.

**"Cognition engine" = only #3.** That gives a clean definition: *the agent that makes the
epistemic judgment, with deterministic tooling, over a transcript infrastructure keeps for
it.*

### It's a family, not one thing

Different kinds of cognitive work = different engines (the L9 sub-protocols):
- converge a group → **SIEP** (the "aligner")
- bargain between two → **SAB** (a negotiator)
- decide who's even in the room → **TFP** (team formation)

Which one you summon depends on what the room is doing. **Mycelium owns the *menu*** — that's
the strategic slot: add new cognitive strategies without waiting on another team.

### Utility — why have them at all

An engine turns a group chat into a **decision with receipts**: a verdict
(converged/rejected), metrics that catch *real alignment vs capitulation*, provenance of how
they got there, and a structured winning position that compiles into the plan. Without one:
eyeballed "seems like we agree," no record, nothing machine-consumable. That's the whole
reason the coordination layer beats "just put the agents in a room."

### Cost is a first-class constraint [decided]

A great engine nobody can afford won't get used. So:
- Engines are **dormant by default — zero cost when idle.**
- **Split cheap-always-on from expensive-summoned:** the backend (already always-on, cheap)
  does the listening/watching and **summons** the engine. The LLM engine never
  idles-but-bills — the listening is free, only the thinking costs.

### Invocation [decided]

An engine wakes three ways:
- **explicit `@`-summon by a human — the floor** (cheapest, most predictable, the default),
- **invoked by an agent**,
- a **configured trigger-word** the cheap watcher matches — an **opt-in power feature,
  default off** (it's the cost knob; whoever runs the stack tunes it).

### Observer vs driver = mode once invoked (neither is always-on)

- **Observer** — one-shot: wake, read the transcript, emit a verdict, sleep. Cheap.
- **Driver** — takes the wheel: runs the rounds / mediates the multi-step engagement ("you
  can't be trusted to do this one-by-one, I'll step in"), then steps aside. More passes,
  only when mediation was judged worth it.

### The intended shape: a cost-proportional escalation ladder

Agents talk for free → someone fires a cheap **observer** spot-check ("are we there yet?") →
escalate to an expensive **driver** *only* when the observer says they're stuck / talking
past each other. Compute scales with how hard the coordination actually is, not with uptime.
**Most rooms never pay for a driver.**

### This settles the resilience question

**Backend = the cheap always-on layer** (moderator + persister + trigger-watcher). **Engine
= summoned, ephemeral, expensive.** No single fragile always-on brain — the always-on part is
dumb and cheap, the smart part is transient. The cost constraint forced the clean split.

---

## 16. Services & networking topology [SKETCH]

### The backend collapses to local files + a thin process [proposed direction]

Once SLIM-native, walk through what the DB still does: messages → SLIM, presence → SLIM,
subscriptions/NOTIFY/SSE → SLIM subscriptions, rooms → folders, memory content → markdown.
**The only remaining job for Postgres/AgensGraph is the semantic search index.**

And a search index over *one person's* memory (hundreds–low-thousands of entries) doesn't
need a database: **a JSONL sidecar of embeddings + brute-force cosine in-process** is fine at
that scale. So:

- **Content** → markdown files (canonical).
- **Search index** → a local **JSONL** file (embeddings + metadata); brute-force cosine.
- **Postgres / AgensGraph → dropped entirely.**

The "backend" stops being a heavy service and becomes **local files + a thin always-on
process** (persister / trigger-watcher / UI-server). This matches mycelium's own "rooms are
folders" ethos. `[OPEN caveat]` brute-force cosine slows in the tens-of-thousands — not the
target vertical; add a real index the day it matters. Embeddings are still computed locally
(sentence-transformers, already local) — a dependency, not a server.

### What runs (SLIM-native + JSONL)

| Process | Role | Notes |
|---|---|---|
| **SLIM node** | the hub — routes/fans out messages | `ghcr.io/agntcy/slim`, one container |
| **thin local process** | persister, trigger-watcher, UI-server, memory read/write | replaces the FastAPI+Postgres backend; lightweight |
| **local files** | markdown (content) + JSONL (search index) | canonical store; no DB |
| **connectors + summoned engines** | connect to the hub as clients | per §5 / §15 |

No database container. The heaviest thing in the stack is now the SLIM node itself.

### The hub / rendezvous — one command, whoever runs it

`mycelium hub host` spins up a SLIM node and prints an address; others `mycelium connect
<address>`. **The topology is identical regardless of who runs it — only *location*
differs.** What the location must satisfy is **reachability**:

- **localhost** (solo) — trivial.
- **LAN** (same office / VPN) — self-host trivial; copy the LAN IP. This is where
  `mycelium hub host` shines.
- **Open internet** (two home NATs) — needs a *reachable* node: a tunnel/port-forward, or a
  hosted one. The only case where hosting earns its keep.

### Hosting stance

- **[decided] Self-hosted is the default and the real story.** Mycelium is *not* in the
  business of running a hosted rendezvous as its model.
- **[open / maybe] A minimal mycelium-hosted rendezvous as an optional getting-started
  on-ramp** — faster time-to-value ("see it work in 30 seconds"). Deliberately kept minimal
  and framed as a PoC convenience, not the product.
- **Why it's more defensible than it sounds:** SLIM groups use **MLS end-to-end
  encryption**, so an intermediate node sees **only ciphertext**. A hosted rendezvous would
  be a **dumb encrypted-packet forwarder that cannot read the traffic it routes** — no
  plaintext user data on our box. That materially lowers the risk profile vs "we host users'
  agent conversations," and it gives the central-rendezvous idea a home without betting the
  architecture on it. Whoever runs the room host also owns that room's trigger-word tuning
  (§15).

---

## Source pointers

- SLIM: github.com/agntcy/slim · bindings: github.com/agntcy/slim-bindings ·
  npm `@agntcy/slim-bindings` 1.4.1 · PyPI `slim-bindings`
- A2A: github.com/a2aproject/A2A · JS: github.com/a2aproject/a2a-js (`@a2a-js/sdk` 1.0.1)
- A2A-over-SLIM: github.com/agntcy/slim-a2a-python (v0.6.1) · npm `@agntcy/slim-a2a` 0.1.0
- L9 / IOC: github.com/outshift-open/ioc-protocols-models · PyPI `ioc-l9-all-models`
```
