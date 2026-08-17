# Docs reframe: assessment & tracking

Working plan for bringing the rest of the docs in line with the new framing
(humans + agents in a shared workspace; honest and understated; not a
negotiation product). Companion to #450. The overview, quickstart, users, and
adapters pages already landed; this tracks everything downstream.

Docs source: `mycelium-cli/src/mycelium/docs/*.md` (+ `guides/`) generates the
site via `docs/generate_docs.py`. Some landing/adapter HTML is hand-kept in
`docs/*.html`.

## Cross-cutting themes (highest leverage)

1. **Pain-pitch relapses.** `guides/structured-memory.md` still has
   "## The Problem → the next agent starts from scratch." Kill this framing
   wherever it recurs (starts from scratch / from zero / no memory).
2. **Negotiation is still the center of gravity.** `rooms.md` Coordination is the
   aligner arc; `episodes.md` + `aligner.md` are wall-to-wall NEGMAS. Lead with
   shared memory + the coordination surface; treat negotiation as one summonable
   engine, not the definition of coordinating.
3. **Two competing "what's left to do" models.** `rooms.md` Typed events
   (`source_event`/`action`/`concern`, the #493 live ledger) vs `plan.md`'s frozen
   compiled `plan/tasks.md`. Reconcile: the event ledger is the live surface; the
   plan should be reframed around it or merged.
4. **Infra jargon.** hub/spoke/thin-client/moderator/MLS in `architecture.md`,
   `rooms.md`, and `guides/hub-and-spoke.md`. Replace with plain "runs on a server
   your team connects to"; SLIM demoted.
5. **Self-deprecating hedges.** `metrics.md` "minimal in v1 / future work." State
   what exists; experimental is implied once up front.
6. **Memory undersells itself (#600).** `memory.md` + `structured-memory.md` are
   short-note-centric; the interlinked-wiki / long-lived-docs story never arrives.
7. **Em dashes + internal/legacy residue** across most pages (e.g. "legacy
   engine.runtime coerces to backend", "deferred to a future herdr integration").

## Proposed reorg (concept flow / sidebar)

Current: Rooms · Users & Teams · Episodes · Memory · Plan · L9 · Engines
Suggested: **Rooms → Memory → Coordination (events + plan merged) → Engines
(Aligner, Synthesizer) → Users & Teams → Advanced (L9, Episodes under Aligner)**

## Task list

- [ ] **1. Mechanical sweep**: em dashes DONE (docs site + entire CLI source +
      SKILL.md/cursor rules; only deploy-config YAML comments left, not docs);
      "primitive" DONE. Still: hub/spoke/thin-client, the structured-memory
      "Problem" line, across all concept docs + guides.
- [ ] **2. rooms.md + plan.md + events reconciliation** (coordination-surface
      reframe; biggest conceptual win).
- [ ] **3. Demote negotiation**: fold `episodes.md` into `aligner.md`, move L9 to
      an advanced tier, reorder the sidebar.
- [ ] **4. memory.md #600 rewrite**: long-lived docs / interlinked wiki (largest,
      most net-new writing).
- [ ] **5. Guides + troubleshooting**: rename hub-and-spoke guide, reflect the
      three-tier identity framing in auth/keycloak/spire, em-dash + jargon pass on
      troubleshooting.

## Per-page notes

- **rooms.md**: lead with the shared space; pull Typed events up; strip
  moderator/MLS/SLIM-channel from the opening.
- **episodes.md**: fold into the Aligner page (episode only exists for a
  negotiation).
- **plan.md**: reframe around the live ledger (#493) or merge with events; drop
  "frozen compiled checklist" as the definition.
- **engines.md**: closest to right; trim backend-side/Pi/legacy-runtime asides.
- **aligner.md**: fine as a deep page; should read as "one engine you summon."
- **synthesizer.md**: solid, light touch.
- **l9-protocol.md**: good writing but advanced; demote out of the top flow.
- **metrics.md**: de-hedge.
- **architecture.md**: rewrite Deployment Modes in plain topology language; cut
  legacy/deferred asides.
- **guides/structured-memory.md**: kill "## The Problem"; align with #600.
- **guides/hub-and-spoke.md**: rename away from the jargon.
- **guides/auth.md / keycloak-oidc.md / spire-identity.md**: reflect the
  three-tier identity framing; lower priority.
- **troubleshooting.md**: em-dash + jargon pass only.
