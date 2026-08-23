# Naming audit: cute names for boring concepts

A sweep of `fastapi-backend/`, `mycelium-cli/`, `mycelium-frontend/` and
`shotkit/` for identifiers that are **evocative instead of obvious** — a name
that reads as a metaphor when a plain, industry-standard term already exists.

The trigger was a real bug: an optimistic-UI mechanism in the board had been
named `overlay`, and a reader (human or agent) who knows the pattern by its
standard name could not find it, and a reader who found it could not tell what
it did. The cost of a cute name is not aesthetic. It is that nobody can grep for
it, nobody can transfer knowledge into it, and everyone re-derives what it does.

The target style is deliberately unfashionable: name the thing after **what it
is**, in the words the rest of the industry already uses, even when that is
longer and duller. `OptimisticFieldEdits` over `overlay`. Not
`AbstractOptimisticFieldEditStateContainerFactory` — the goal is boring, not
bureaucratic.

## The rubric

A name is a finding if it fails one of these:

1. **The standard-term test.** Does this concept already have a name the
   industry uses? If yes, use that name. (`overlay` → optimistic state.)
2. **The cold-read test.** Can a competent stranger guess, from the name alone,
   roughly what it holds or does — without reading the docstring?
3. **The collision test.** Does this word already mean something *else* in this
   codebase, or something well-known and different outside it? (`Liveness` means
   a health probe everywhere except here.)
4. **The one-concept-one-word test.** Is the same concept spelled two ways in
   different modules? (`custody` and `lease` are the same thing.)
5. **The metaphor-debt test.** Does the name only make sense if you have read the
   docstring that establishes the metaphor? A name that needs a glossary entry is
   a name that failed.

A name is **not** a finding merely because it is short, domain-specific, or
product-facing. `aligner`, `synthesizer` and `room` are product vocabulary; they
are covered in "Deliberately left alone" below.

---

## Tier 1 — clear wins, low blast radius

These are internal names with no contract, no wire format and no user-facing
surface behind them. Renaming is a mechanical refactor.

### 1.1 `overlay` → optimistic edits (the motivating case)

| | |
|---|---|
| **Where** | `mycelium-frontend/src/components/board/room-board.tsx:116`, `197`; `mycelium-frontend/src/lib/board/projection.ts:165`, `190-192` |
| **Now** | `const [overlay, setOverlay] = useState<Record<string, Record<string, unknown>>>({})`, `ProjectionInput.overlay`, `echoLocal(...)` |
| **Problem** | Fails the standard-term test hard. In UI code `overlay` means a modal scrim (which this repo *also* has — `DialogOverlay` in `ui/dialog.tsx:26`, `KeyBadge overlay` in `key-badge.tsx:17`). The board's `overlay` is unrelated: it is local field edits applied on top of server state until the write lands. That is **optimistic state**, and it has been called that since at least Apollo/Relay. |
| **Suggest** | `overlay` → `optimisticEdits`; `setOverlay` → `setOptimisticEdits`; `ProjectionInput.overlay` → `optimisticEdits`; `echoLocal` → `applyOptimisticEdit`. |

Related in the same file: `const [echo, setEcho]` (`room-board.tsx:128`) is not
an echo of anything — it is the status/refusal message shown under the board.
`statusMessage` / `setStatusMessage`.

Note the collision is already visible in the code: `room-board.tsx:202` says
"the overlay is the optimistic echo" — the comment is doing the work the name
should have done.

### 1.2 `brain` → LLM session

| | |
|---|---|
| **Where** | `fastapi-backend/app/services/pi_brain.py:298` (`PiBrain`), `:237` (`PiBrainError`); `mycelium-cli/src/mycelium/engine/brain.py`; `aligner.py:162,181,414,424` (`brain_factory`, `_make_brain`); `synthesizer.py:296`, `task_compiler.py:216`, `llm_health.py:423` |
| **Now** | "A Pi-backed cognitive brain for mycelium's *internal* agents." |
| **Problem** | Fails the cold-read test. The class is a **persistent subprocess wrapper around one `pi -p --session` process, exposing a `(prompt, *, system, temperature) -> str` callable**. That is an LLM session/client. "Brain" implies cognition living here; the cognition lives in the model. It also makes the seam harder to describe: `brain_factory` is a *session factory*. |
| **Suggest** | `PiBrain` → `PiSession` (or `PiLlmSession`); `pi_brain.py` → `pi_session.py`; `brain_factory` → `session_factory`; `_make_brain` → `_open_session`; local `brain = PiBrain(...)` → `session = PiSession(...)`. |

This one is high-value because `brain` appears in a log line users see
(`main.py:153`: `"engines wired (… brain=pi via %s)"`) — `llm=pi` reads better.

### 1.3 `Known` → cached status answer

| | |
|---|---|
| **Where** | `fastapi-backend/app/services/status/types.py:143` |
| **Now** | `class Known: ref, freshness, liveness, fetched_at, error` |
| **Problem** | Pure metaphor debt. `Known` is an adjective standing in for a noun, and it is one of the most generic words available. Its docstring — "what the app hands a caller: a value, and how much to trust it" — is a perfect name that was not used. |
| **Suggest** | `CachedStatus`, or `StatusAnswer` if you want to keep it transport-neutral. |

### 1.4 `Liveness` → external item state

| | |
|---|---|
| **Where** | `fastapi-backend/app/services/status/types.py:104` (and `Freshness` at `:83`) |
| **Problem** | Collision test. `liveness` is a term of art for a health probe (k8s `livenessProbe`, and this repo has real health endpoints). Here it means "a provider's reading of an external thing" — a GitHub PR's state, say. A reader hitting `Liveness` in a status module will assume health-checking. |
| **Suggest** | `ExternalState` / `UpstreamState` (the field it lands on is already called `upstream`, so `UpstreamState` also fixes the word/field mismatch). Keep `Freshness` — that one is accurate. |

### 1.5 `Ok` / `Err` / `Outcome` → fetch result

| | |
|---|---|
| **Where** | `fastapi-backend/app/services/status/types.py:121`, `130`, `139` |
| **Problem** | Rust idiom transplanted into Python, at module top level, with names so generic that any `from ... import Ok` reads as noise at the call site. Python has no `Result` convention to lean on, so the borrowed names carry no meaning here. |
| **Suggest** | `FetchSucceeded` / `FetchFailed` / `FetchOutcome` (or `ProviderOk`/`ProviderErr` if you want to keep the shape and just disambiguate). |

### 1.6 `Digest` / `digest()` → activity summary

| | |
|---|---|
| **Where** | `mycelium-cli/src/mycelium/board/activity.py:56`, `:269` |
| **Problem** | Collision test: in a codebase with crypto, MLS and content hashing, `digest` means a hash. Here it is a date-ranged rollup of activity events. Also `digest(days, frm, to)` reads as a verb applied to days. |
| **Suggest** | `ActivitySummary` / `summarize_activity(...)`. |

### 1.7 `_kick` → schedule a refresh

| | |
|---|---|
| **Where** | `fastapi-backend/app/routes/status.py:120` |
| **Now** | `def _kick(runtime, refs, now) -> bool` — spawns a background refresh task for due refs. |
| **Suggest** | `_schedule_background_refresh`. The docstring already says it: "Refresh whatever is due, in the background." |

### 1.8 `CoordSessionShim` → presence session

| | |
|---|---|
| **Where** | `fastapi-backend/app/services/local_state.py:47` |
| **Problem** | "Shim" names the *history* (it replaced a DB row), not the thing. In a year nobody will know what it is a shim for, and the name will still be there. Also `Coord` is an abbreviation that saves five characters. |
| **Suggest** | `PresenceSession`. Nothing else needs to change — the attribute names are already what `model_validate` expects. |

While here: `local_state.py` itself is a vague module name for "the in-process
message/session/participant store." `in_memory_store.py` says it.

### 1.9 `hello.py` / `HelloEngine` → wiring probe engine

| | |
|---|---|
| **Where** | `fastapi-backend/app/services/hello.py:100` |
| **Problem** | Reads as tutorial scaffolding, so a reader's first instinct is "this is example code, delete it." It is not: it is the **production probe for the summon path**, and its own docstring argues for exactly that. A name that invites deletion is a dangerous name. |
| **Suggest** | `ProbeEngine` / `probe_engine.py`, or `EchoEngine` if the registered `kind` string must stay short. If the user-facing `--kind hello` is worth keeping, keep the string and rename the module/class. |

### 1.10 `earcon` → board sound

| | |
|---|---|
| **Where** | `mycelium-frontend/src/lib/board/earcons.ts:30` (`type Earcon`), `:37` (`MOTIFS`), `:91` (`earcon(name, volume)`); consumed at `components/board/room-board.tsx:46`, `135-136`; `lib/audio-ping.ts:40` (`motif`) |
| **Problem** | "Earcon" is a real HCI term (Blattner, 1989) — but a term of art nobody outside auditory-display research has met is indistinguishable from an invented one at the call site. `earcon(name, volume)` tells a reader nothing; `type Earcon = Verb \| "needs_you" \| "answer" \| "capture" \| "move"` tells them less. It fails the cold-read test, which is the test that matters: the standard-term test is about *using* the word the industry uses, not about whether a defensible citation exists. |
| **Suggest** | `earcons.ts` → `board-sounds.ts`; `type Earcon` → `BoardSound`; `earcon(...)` → `playBoardSound(...)`; `MOTIFS` → `SOUNDS`. `motif` in `audio-ping.ts` can stay — it is the generic "play these notes" primitive and reads correctly as music, not as an event vocabulary. |

Blast radius is one module and one consumer (a `play` callback in
`room-board.tsx`), so this is among the cheapest renames on the list. The
module's design rationale — one motif per state change, intervals rather than
volume, everything under 400ms — is good and survives the rename untouched; it
is only the word that is doing no work.

### 1.11 Miscellaneous Tier-1 renames

| Where | Now | Suggest |
|---|---|---|
| `fastapi-backend/app/services/status/cache.py:27` | `Entry` | `CacheEntry` |
| `fastapi-backend/app/services/status/discovery.py:49` | `Discovered` | `DiscoveredRefs` (participle-as-noun; fails cold read) |
| `fastapi-backend/app/services/status/types.py:157` | `Context` (Protocol) | `ProviderContext` — collides with `l9_models.py:51 class Context` |
| `fastapi-backend/app/services/links.py:124` | `Expansion` | `TransclusionResult` — the module's own word for the feature is transclusion |
| `mycelium-cli/src/mycelium/board/custody.py:99` | `spent(stamped_at, ttl, now) -> float` | `elapsed_fraction(...)` — "spent" alone says neither what nor of what |
| `mycelium-frontend/src/lib/board/custody.ts:117`, `item.ts:125` | `leaseSpent`, `ttlSpent` | `leaseElapsedFraction`, `ttlElapsedFraction` |
| `mycelium-cli/src/mycelium/commands/agent.py:57` | `_bail_root_owned` | `_abort_if_root_owned` |
| `mycelium-frontend/src/components/board/board-bits.tsx` | `board-bits` | Junk-drawer name for a 400-line file of row cells and chips. `board-cells.tsx`, or split by what it draws |
| `mycelium-cli/src/mycelium/engine/runtime.py:65`, `:247` | `EngineDrive`, `drive_over_channel` | `NegotiationRunner`, `run_negotiation_over_channel` — "drive" is a verb doing noun work |
| `fastapi-backend/app/services/mediator.py:412` | `LiveNegotiator` | `RemoteAgentNegotiator` — "Live" is doing no work; the distinction is *who answers*, a real agent over SLIM |
| `mycelium-frontend/src/lib/board/fields.ts:49-70` | `str`, `num`, `arr`, `bool` | `fieldAsString`, `fieldAsNumber`, `fieldAsList`, `fieldAsBool` — four-letter coercers imported bare into six modules read as types, not calls |

---

## Tier 2 — worth renaming, but the vocabulary is frozen

These are wrong for the same reasons, but each is declared in
`contracts/board-vocabulary.json` and carried in three implementations
(frontend, CLI, backend), with drift tests on each side. Renaming means bumping
the contract `version` and touching all three copies — real work, but the
contract is exactly the mechanism that makes it *safe* work.

### 2.1 `lens` → attention filter

`Lens` / `LENSES` / `lensOf` / `lensCounts` / `LENS_OF_CUSTODY`
(`mycelium-frontend/src/lib/board/item.ts:47-52`, `custody.ts:70`,
`mycelium-cli/src/mycelium/board/custody.py:169`,
`contracts/board-vocabulary.json` → `lenses`, `lens_of_status`).

The three "lenses" are `needs_you` / `in_flight` / `resolved`: saved filters over
rows. "Lens" is an aesthetic word for a filter, and the codebase has to keep
explaining it ("the steer-lens", "the firehose is opt-in"). `AttentionFilter`,
or just `WorkFilter`, needs no gloss. The wire values themselves
(`needs_you` etc.) are good and should stay.

### 2.2 `verb` → row action

`Verb` / `VERBS` / `applyVerb` / `VerbContext` (`item.ts:147-190`,
`contracts/board-vocabulary.json` → `verbs`, `verb_keys`).

The set is `claim | release | resolve | block | unblock | promote | dismiss` —
these are **actions/commands a user takes on a row**. "Verb" names their part of
speech, not their role in the system, which is why `VerbContext` is hard to read:
it is the context an *action* executes in. `RowAction` / `ROW_ACTIONS` /
`applyRowAction` / `RowActionContext`.

### 2.3 `cockpit` → triage view

`ViewMode = "cockpit" | ...` (`view.ts:28`), `BoardCockpit`,
`board-cockpit.tsx`, and ~15 comment references ("the cockpit's fastest read",
"the cockpit likes").

It is the default grouped view filtered to one attention filter. `"triage"` /
`TriageView` / `board-triage.tsx` says that. Note this one leaks into a
persisted saved-view config, so it needs a migration or a read-time alias.

---

## Tier 3 — collisions and split concepts

These are the most expensive bugs in the list, because they mislead rather than
merely obscure.

### 3.1 `custody` means two unrelated things

| Meaning | Where |
|---|---|
| **Cryptographic key custody** — the hub holds per-actor MLS/SignerJwt keys server-side | `fastapi-backend/app/services/custody.py`, `MYCELIUM_CUSTODY_STORE_SECRET`, `<data>/custody/{room}/{handle}/` |
| **A lease on a work row** — who is currently holding a task, draining on a TTL | `mycelium-frontend/src/lib/board/custody.ts`, `mycelium-cli/src/mycelium/board/custody.py`, `contracts/board-vocabulary.json` → `custody`, the `custody` frontmatter field |

Two modules named `custody`, in the same repo, sharing no concept. The
key-management sense is a genuine term of art and is documented as such
(`custody.py` even explains the custodial-wallet analogy). The board sense is a
lease — and the board sense is the one that should move.

**Suggest:** the board's `custody` → `assignment` or `holder` (the field), and
the state enum stays as-is (`unclaimed | held | released | expired | resolved`
reads fine under either name). Keep `custody` for keys only.

### 3.2 …and the board's lease is also called `lease`

The backend half of the *same* board feature lives in
`fastapi-backend/app/services/leases.py`, whose first line is "Custody leases".
So one concept has two names across the seam (`leases.py` ↔ `custody.ts`), while
the name it shares with the other module means something else entirely. Both
halves should end up on one word, and it should not be `custody`.

There is a third, unrelated `lease` in the codebase — the **presence lease** that
holds server-side room membership between `await` calls
(`routes/participate.py`, `members()`). That one is legitimately a lease.
Disambiguating the work-row one to `assignment` clears this up too.

### 3.3 `refusal_for` defined twice, differently

`mycelium-cli/src/mycelium/board/fields.py:51` (why a row refuses a *field
write*) and `mycelium-cli/src/mycelium/board/custody.py:203` (why a row refuses a
*claim*). The frontend got this right — `fieldWriteRefusal` and `custodyRefusal`
— and the CLI should mirror it.

### 3.4 `Context` defined twice

`fastapi-backend/app/services/l9_models.py:51` (an L9 envelope block, vendored)
and `fastapi-backend/app/services/status/types.py:157` (the protocol a status
provider is handed). The vendored one cannot move; the local one should be
`ProviderContext` (see 1.11).

---

## Tier 4 — borderline, listed for the record

Judgment calls. Each is defensible; each also costs a reader a beat.

- **`upstream`** (`status/types.py:78` `ROW_FIELD`, `attachUpstream`,
  `UPSTREAM_FIELD`) — well-defended in the docstring, but collides with git's
  `upstream` and with the phrase "upstream service." `external` /
  `externalStatus` is unambiguous.
- **`RoomPersister` / `persister.py`** — an agent-noun coinage for what is a
  message ingest + transcript store. `TranscriptStore` is duller and clearer.
  Wide blast radius; low priority.
- **`heat_level`** (`board/activity.py:109`) — heatmap intensity. Fine in context,
  slightly cute out of it.
- **`KindGlyph`** (`board-bits.tsx`) — `KindIcon`, to match `lucide-react` and the
  neighbouring `KindBadge`.
- **`snap` / `snap_offer` / `offer_snap.py`** — snap-to-grid is standard. Keep.
- **`pump` / `startPump`** (`shotkit/src/pump.mjs`) — standard in media pipelines.
  Keep.
- **`spores.py`** (`mycelium-cli/src/mycelium/animations/`) — branded ASCII art for
  a project named Mycelium. Keep; product identity is a legitimate reason.

---

## Deliberately left alone

Not everything evocative is a finding. These stay:

- **`aligner`, `synthesizer`, `room`, `episode`, `memory`, `skill`** — product
  vocabulary, used in the CLI, the docs and the UI. Renaming them would be a
  rebrand, not a refactor. One caveat: `aligner.py` and `mediator.py` coexist
  while `CLAUDE.md` says "the aligner *is* the mediator" — worth one clarifying
  comment at the top of each, not a rename.
- **L9 / SSTP / IOC names** — `Epistemic`, `Semantic`, `Provenance`, `Kind`,
  `Team`, `PROTOCOL = "SSTP"` (`l9_models.py`, `l9.py:41`). Vendored from
  `outshift-open/ioc-protocols-models`; these are wire-format names we do not own.
  Renaming them would break the thing the contract tests exist to protect.
- **NEGMAS names** — `SatisfactionOrderedSAO`, `SAONegotiator`. Long and precise;
  exactly the target style.
- **`bus.py`, `event_sweep.py`, `electLeader`, `capture`** — pub/sub bus, TTL
  sweep, leader election, and GTD-style capture are all standard terms.
- **`custody` in `services/custody.py`** — correct term of art, correctly used,
  and explained in the module docstring. It is the *board's* use that should move.

---

## Suggested sequencing

1. **Tier 1, one PR per area.** No contracts, no wire, no user surface. The
   `overlay` → `optimisticEdits` and `PiBrain` → `PiSession` renames are the two
   with the best ratio of clarity gained to lines touched.
2. **Tier 3.1/3.2 next**, as one PR. This is the only finding with a real
   correctness risk attached — two `custody` modules meaning different things is
   how someone eventually wires the wrong one.
3. **Tier 2 last**, if at all, and each on its own. Bump
   `contracts/board-vocabulary.json` `version`, update all three copies, let the
   existing drift tests prove it landed. `cockpit` additionally needs a read-time
   alias for persisted saved views.

None of this is urgent. All of it is the kind of thing that gets harder every
month it is deferred, because each new caller is another rename site.
