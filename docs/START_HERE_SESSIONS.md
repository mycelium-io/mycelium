# START HERE — Sessions as a first-class concept (tag-on-the-room model)

> **You own re-introducing the session concept.** The SLIM-native rewrite kept
> the *machinery* of coordination but quietly dropped "session" as a thing a user
> can see, name, and reason about. This brief restores it — as a **tag/metadata
> layer over the existing room channel**, not a separate space — and PoCs that it
> works end to end. When it lands, it folds into `START_HERE_DOCS_REWRITE.md`
> (which currently declares sessions "gone" — that stance changes because of this
> work).

This is a **small, sharp** build. Most of the substrate already exists; the job is
to make it *distinct, groupable, and legible*, not to build a subsystem.

## Status (as built)

- ✅ **Rung 1 — unique episode ids.** `aligner.py` no longer hardcodes
  `short_id="align"`; each convening gets a unique id (`_new_episode_id`).
  Regression test proves two convenings → two distinct `log/episodes/*` records.
- ✅ **Rung 2 — episode tag on the transcript (backend).** Messages carry their
  `episode` (list store + SSE + `MessageRead`); `list_messages` takes an
  `episode=` filter. Frontend `Event` model threads `episode` through; the visual
  fold UX is the remaining frontend piece (best iterated live).
- ✅ **Rung 3 — membership scoping.** `@aligner @a @b` scopes the run to @a/@b;
  co-summons thread through the summon hook (`persister` → `room_channels` →
  `aligner._scoped_participants`). Tested.
- ✅ **Rung 4 — live in-progress episode.** `episodes.py` surfaces the open
  episode (`outcome:"open"`) from the moderator's lifecycle before the record
  lands. Tested.
- ⬜ **Rung 5 — CLI + docs vocabulary migration.** Precondition confirmed: the
  live `session join`/`await` **commands are already gone** — only prose/help-text
  references remain. Pure docs work; overlaps `START_HERE_DOCS_REWRITE.md` §8.
- ⬜ **Frontend fold UX** (collapse an episode's turns under a "Session {id}"
  unit) and the **sub-room vestige cleanup** (below) remain.

---

## 1. The decision

**A session is a tag on the room's SLIM channel — not a separate channel.**

We considered a real "breakout room" (a second SLIM group channel scoped to the
negotiating agents). It's the cleaner spatial model, but it requires **connector
work on every member host**: a daemon connector today holds exactly one channel
subscription per `(room, handle)` (`connector.py`: one `SlimIdentity(workspace,
room, handle)`, one `listen_for_session()`, one `receive_message` loop), and
`connector_targets` only spins up connectors for rooms in `daemon.toml`. A
breakout channel would get no connector at all. Teaching connectors to *follow
into a breakout* is real, cross-host work.

The tag model needs **zero** of that. Negotiation keeps running on the one room
channel exactly as it does now; the session is metadata that scopes, groups, and
names that activity. That's the play.

---

## 2. Why this exists

The old (CFN-era) session was **deliberate and agent-driven**: agents ran a
`session join`, waited for quorum, posted positions, and the coordination_session
tracked lifecycle. A whole song-and-dance — because the *agents* owned the
lifecycle.

The pi-agent mediator **absorbed all of that**. `aligner.mediate` discovers the
issues, `@`-addresses one agent per turn over the channel, interprets each reply,
and decides termination. Agents went from drivers to *reactive* — a standing
daemon connector cold-spawns a turn only when an addressed message arrives
(`should_wake` → `integration.spawn`). There is no join command and nothing for
an agent to actively manage.

So the session didn't need to *disappear* — its **lifecycle owner moved** from the
agents to the mediator. The right frame now:

> **A session is *convened* by the mediator, not *joined* by the agents.**
> A summon opens it, the mediator drives it, the verdict closes it. Agents get
> pulled in and spat back out.

That reframe fits both your breakout-room intuition (a bounded space where things
get sorted out, with its own record) and the ad-hoc pi reality (no agent-side
ceremony).

---

## 3. Ground truth — what already exists (the leverage)

Before writing any code, know that **the L9 episode already *is* the session**,
and it is already partly surfaced:

- **The tag is already on every envelope.** `l9.episode_urn(parent_room,
  short_id)` → `urn:ioc:mycelium:episode:{room}:{short_id}` rides every L9
  message's `header.message.episode`. Agent replies inherit it (`build_reply`
  copies `episode_of(woke)`). **This URN is the session tag.**
- **A durable per-session record already lands.** On close,
  `l9_episode.write_episode_record` writes `log/episodes/{short_id}.md` in the
  parent room: frozen roster, outcome (`converged`/`rejected`), MPC/GAR/SCR
  metrics, `assignments`, `plan_file`, and the full causal L9 envelope chain.
- **A read API already projects it.** `app/routes/episodes.py`:
  - `GET /rooms/{room}/episodes` — summaries (short_id, episode urn, topic,
    outcome, participants, metrics, assignments, plan_file, message_count).
  - `GET /rooms/{room}/episodes/{short_id}` — one session + its envelope chain.
- **The UI inspector already renders these** (shipped in the Step 10 protocol
  inspector).

So we are not building "sessions" from nothing. We are making the episode
**distinct per convening, groupable in the live feed, and named as a session.**

---

## 4. The core gap

**Every convening reuses the same session id.** `aligner.py` hardcodes
`short_id="align"` (in `mediate` and `drive`; see `episode = l9.episode_urn(room,
"align")` and `open_episode(short_id="align")`, plus `"live"` in
`_episode_from_records`). Consequences:

1. Every negotiation in a room shares **one** episode URN → the session tag can't
   distinguish two negotiations.
2. Every close **overwrites the same `log/episodes/align.md`** → the previous
   session's record is clobbered.
3. The live room transcript can't be sliced per session — `list_messages`
   (`messages.py`) filters by sender/type/kind/status/since, but **not by
   episode**.

Fix the id, and sessions become distinct, addressable, and non-clobbering — with
the record + read API + inspector already in place.

---

## 5. Design — session ≡ episode, 1:1

- **One session = one convening = one episode.** A summon opens a session; the
  verdict closes it. A re-negotiation is a *new* session (new id, new record). No
  nested hierarchy.
- **The session id is a short, unique, human-legible token** (e.g. a short
  timestamped/random slug). It becomes the episode `short_id`, so it flows into
  the URN, the `log/episodes/{id}.md` filename, and every envelope on the wire —
  for free.
- **Everything stays on the room channel.** The session is metadata; no second
  channel, no connector change, no sub-room directory.

### Terminology — unify on "episode" (decided)

The concept is an **episode**, top to bottom — protocol, API, CLI, docs, UI.
It's already the L9 term (`episode_urn`, `l9_episode`, `log/episodes/*`), the API
route (`/rooms/{room}/episodes`), and the record dir. Rather than maintain a
session/episode split, we adopt "episode" as the single user-facing name and
**retire the "session" vocabulary**.

That has a migration cost, tracked as its own rung (§6, "CLI + docs vocabulary
migration"): the old CFN-era `session join`/`session await` **commands** appear
already removed in the rewrite (only references remain, not live commands —
verify before writing prose), but "session" language still lingers in CLI help
text, the bundled CLI docs, the adapter `SKILL.md`, and openclaw assets. All of
it moves to "episode" — and, while there, to the current *summon `@aligner`* flow
rather than the removed join/await dance.

---

## 6. The rungs

Ship in order. Rung 1 alone delivers distinct, non-clobbering sessions; 2 makes
them legible in the live feed; 3–4 are polish.

### Rung 1 — Unique session ids (foundational, small)
Replace the hardcoded `"align"`/`"live"` short_id with a generated unique id per
convening.
- `aligner.py`: in `mediate` (and `drive`, `_episode_from_records` if kept),
  generate one session id at the top of the run and thread it through both
  `l9.episode_urn(room, session_id)` and `open_episode(short_id=session_id)` so
  the URN and the record filename match.
- Keep it short + filesystem-safe (it's a memory-file key: `log/episodes/{id}`).
- **DoD:** two `@aligner` convenings in one room produce **two** distinct
  `log/episodes/{id}.md` records and two distinct episode URNs on the wire.

### Rung 2 — Group the live transcript by session
Make the room feed sliceable and foldable by session.
- Surface the session tag on room messages: `TranscriptRecord.content` already
  carries the L9 envelope (episode derivable). Ensure the message read path
  (`messages.py` `list_messages` → `local_state` / persister) exposes the episode
  so a client can group by it.
- Add an `episode`/`session` query filter to `list_messages` (mirrors the
  existing `kind`/`status`/`since` filters).
- UI: fold a session's mediator ticks + per-turn prose under a collapsible
  "Session {id}" unit; keep the summon and the `commit` verdict prominent in the
  room. (Reuse the inspector's existing episode projection.)
- **DoD:** the room stays readable during a negotiation — a human sees "session
  opened → agreement" without wading through every SAO tick, and can expand the
  session to see the full exchange.

### Rung 3 — Membership scoping (optional)
Let the summoner name who's in the session: `@aligner @a @b` negotiates only
`@a`/`@b` instead of `mediate` grabbing all room members
(`participants = [m for m in members(room) if m != me]`). The frozen roster is
already recorded via `open_episode(agents=...)`; this just narrows the input.
- **DoD:** a room with 4 agents can run a 2-agent session; the other two are
  untouched and the record shows the scoped roster.

### Rung 4 — Live (in-progress) session object (optional)
Surface a session *while it runs*, not only at close. `open_episode` on the
manager already tracks the active episode in memory; expose it (e.g. a
`status: open` entry in the episodes list) so the UI can show "session in
progress" before the record lands.
- **DoD:** the episodes/sessions list shows an open session mid-negotiation.

### Rung 5 — CLI + docs vocabulary migration ("session" → "episode")
Retire the "session" vocabulary across user-facing surfaces (the concept is
"episode" now — §5). Grounded targets (grep before editing; the list drifts):
- **CLI help/prose:** `commands/room.py` (help text still points at
  `mycelium session join …`), `commands/doctor.py` sandbox messages.
- **Bundled CLI docs:** `src/mycelium/docs/sessions.md` (rewrite or rename to
  `episodes.md`), `quickstart.md`, `cognitive-engine.md`, `troubleshooting.md`,
  `metrics.md`, `guides/*` — all still describe the removed `session
  join`/`await` flow; move them to the summon-`@aligner` episode flow.
- **Adapter skill + openclaw assets:** `assets/skills/mycelium/SKILL.md` and the
  openclaw plugin assets referencing `session join`.
- **Confirm the commands are actually gone** first: if any live `session`
  Typer command remains, decide alias-vs-remove with the owner.
- **DoD:** `grep -rniE '\bsession (join|await|spawn|leave)\b'` over the CLI +
  docs returns nothing describing it as a current flow.
- *Note:* this rung overlaps `START_HERE_DOCS_REWRITE.md` (§8). If the docs pass
  runs first, hand it this list; if this runs first, it discharges that slice.

### Cleanup (bundle with rung 1 or 2)
Remove the dead `{room}:session:{id}` **sub-room** scaffolding
(`filesystem.py` `_is_session_dir` + the filtering, the
`local_state.CoordinationSession.display_name` `:session:` label) — the tag model
keeps everything in the parent room, so the sub-room vestige is now actively
misleading. Confirm nothing live depends on it before deleting.

---

## 7. The PoC — prove it works

Do this on a live stack (contributor dev flow, see root `CLAUDE.md` →
Local development). Two same-machine agents is enough (don't test
openclaw/hermes — deprecated post-rewrite).

1. Create a room; register + invoke two cold-spawn agents (claude_code); confirm
   both connectors are up.
2. Summon `@aligner` on question A → let it converge/close.
3. Summon `@aligner` again on question B → let it converge/close.
4. **Assert:**
   - `ls .mycelium/rooms/{room}/log/episodes/` shows **two distinct** records
     (pre-rung-1: only one, clobbered — capture that as the before/after).
   - `GET /rooms/{room}/episodes` lists both sessions with distinct ids, rosters,
     and outcomes.
   - The live transcript can be filtered to each session (rung 2), and the room
     read cleanly while each ran.
   - The inspector shows both sessions separately.
5. Record the evidence (paths, API output) in the PR — the claims in this brief
   should rest on an actual run, not assertion.

---

## 8. Fold into the docs rewrite (do this last)

`START_HERE_DOCS_REWRITE.md` §2 lists `session await / the old
coordination-session negotiation flow` under **"Gone."** That's correct for the
CFN *machinery* but must **not** be written as "mycelium has no sessions." After
this work:
- The docs describe sessions as **present**: a session is a mediator-convened,
  tagged negotiation on a room's channel, with its own record and metrics,
  readable via the episodes/sessions API + inspector.
- Keep the honest line that the *old deliberate `session await` join flow* is
  gone — the concept returns, the CFN mechanism does not.
- Update the capability/behavior prose so a reader understands: summon `@aligner`
  → a session is convened → agreement → plan.

Until this lands, do **not** let the docs rewrite enshrine "no sessions."

---

## 9. Non-goals / guardrails

- **No separate SLIM channel.** Everything stays on the room channel. If someone
  wants true breakout isolation later, that's a *separate* effort gated on
  connector-follow work (see §1) — explicitly out of scope here.
- **No connector changes.** If you find yourself editing `connector.py` channel
  subscription logic, you've left the tag model.
- **No agent join command.** Sessions are convened by the mediator, not joined by
  agents. Don't reintroduce agent-side lifecycle ceremony.
- **Don't re-derive the metrics.** MPC/GAR/SCR live in `l9_episode`; the session
  work only tags/groups/names — it never recomputes convergence.
- **Session ≡ episode, 1:1.** Resist making a session a container of multiple
  episodes; a re-negotiation is a new session.
