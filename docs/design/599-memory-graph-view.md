<!-- SPDX-License-Identifier: Apache-2.0 -->
# #599 — Memory graph view

Branch: `599-memory-graph-view`
Issue: [https://github.com/mycelium-io/mycelium/issues/599](https://github.com/mycelium-io/mycelium/issues/599)

## Problem

A room's memories interlink (`[[wikilinks]]`, `![[transclusions]]`, typed relations —
#611), but the only way to see that structure today is one memory at a time, in the
340px rail drawer: outbound links and backlinks for whatever is selected. There's no
way to see the room's link graph as a whole — which memories cluster together, which
are hubs, which are orphaned, which links are broken.

## Goal

A dedicated, full-page force-directed graph at `/room/{room}/graph`: one node per
memory, one edge per resolved link. Click a node to open that memory; hover to see its
neighbors; pan and zoom to explore a larger room.

## Non-goals

- A full-page **reading** surface for one memory (`/room/{room}/memory/{key}`) — that's
  #614, a separate, independently-landing track. This view has no dependency on it;
  clicking a node here reveals the memory in the existing rail via the same
  `focus=memory:{key}` mechanism search results already use (`lib/search.ts`).
- Link autocomplete in a markdown editor — unrelated to visualization; the chat
  composer's `[[` autocomplete already covers the authoring side.
- Frontmatter schema editing (#596).
- WebGL/canvas rendering — see "Rendering approach" below.

## Rendering approach

`d3-force` (headless physics simulation only) + hand-rolled SVG, not a batteries-included
graph library (`react-force-graph`, `cytoscape.js`, `sigma.js`):

- Room graphs here are tens to low hundreds of memories — well within SVG/DOM
  rendering limits (roughly 1-2k nodes); the WebGL libraries earn their complexity at
  thousands of nodes, not this shape.
- `react-force-graph` has known React 19 ref-handling incompatibilities; `d3-force` is
  headless, so it has no React-version coupling at all.
- A hand-rolled SVG graph reuses this app's own design tokens (`--accent`, `--yellow`,
  `--border2`, and a `--graph-ns-1…8` categorical palette added for this view) and
  click/hover idioms directly, instead of fighting a library's own theming or canvas
  hit-testing API. The namespace palette is a theme token rather than a literal so it
  re-tunes for the light canvas instead of staying at dark-mode brightness.
- If a room's graph ever needs to scale to thousands of memories, Sigma.js/WebGL is the
  documented fallback.

The layout itself runs once per graph payload (a fixed tick count, no live animation
loop) — see `lib/memory-graph-layout.ts`.

What gets drawn turns on **whether both ends are real memories in this room**, not on
whether the link resolved:

- Both ends real → a physics link and a line. If the link nonetheless failed
  (`no_anchor`, `not_expandable`), the line is red and dashed, with the error in its
  tooltip. Dropping these would hide a genuine authored connection between two memories
  that both exist, and would make the target read as less-referenced than it is.
- Target isn't a memory here (`not_found`, `cross_room`), or the link points at itself →
  nothing to pull toward or draw to, so no line. It still shows in the summary strip's
  broken count, which is a fact about the *source* memory — the same way the rail's
  link-integrity work reports it — never a phantom edge to nowhere.

"N links" in the summary strip counts only what resolved, so a broken edge is never
folded into the working total.

Two browser details the canvas has to get right, both easy to regress:

- **Wheel-zoom is a native listener**, not React's `onWheel`. React registers wheel
  handlers as *passive*, so `preventDefault()` inside a React handler silently does
  nothing and the browser keeps its own ctrl+wheel page zoom. `memory-graph.test.tsx`
  dispatches a real `WheelEvent` and asserts `defaultPrevented`.
- **The canvas is `role="group"`, not `role="img"`.** ARIA treats an `img`'s descendants
  as presentational, which would hide every node button from assistive tech — and
  testing-library doesn't implement that rule, so the node-click tests would have kept
  passing while real screen-reader users lost the graph entirely.

## Reading a memory without leaving the graph

Clicking a node opens the memory in the same right-hand `DetailDrawer` the Memory rail
uses, over the canvas — not a navigation away to `?focus=memory:{key}`. The graph is the
thing being explored, and its pan, zoom and hand-arranged layout are all unsaved view
state, so bouncing to another page to read one memory would throw away the exploration
that motivated the click. Following a `[[wikilink]]` inside the drawer swaps it to the
target, so a reader can walk the graph without re-aiming at nodes.

The key is resolved with `fetchMemory(room, key)` rather than a lookup in a preloaded
list. The graph payload carries only keys, and the rail's own `navigateToKey` silently
no-ops when the target isn't in the first page of `memories` it happens to have loaded —
here every node is openable by construction.

## Drag to arrange

Nodes can be dragged, and the arrangement is kept in a `Record<key, {x, y}>` that
overrides the force layout per key; a "Reset layout" button appears once anything has
moved. This is cheap *because* the simulation is one-shot: it has already stopped before
anything renders, so a drag is a plain coordinate override with no `fx`/`fy` pinning, no
`alphaTarget` reheating, and no simulation-versus-React ownership to arbitrate. Four
details carry the weight:

- Edges read their endpoints from the live position map, not the layout's baked
  `x1/y1/x2/y2`, which is what keeps a line attached to the node it follows.
- A press only becomes a drag past `DRAG_THRESHOLD` (4px), so the tremor in an ordinary
  click doesn't nudge a node.
- Pointer capture is taken on the `<svg>` rather than the node, so a drag survives the
  cursor outrunning the circle it grabbed. It's called optionally — jsdom doesn't
  implement `setPointerCapture` on SVG elements, and losing it costs only that robustness.
- **Opening is decided on `pointerup`, never by an `onClick` on the node**, and this is
  load-bearing rather than stylistic. Capturing the pointer retargets the browser's
  follow-up `click` to the capture element, so a node-level `onClick` stops firing the
  moment a press is captured — which is precisely the bug the first cut of this shipped
  with: dragging worked, clicking silently did nothing. The canvas is also the only place
  that knows whether the press became a drag, so it's the right owner of the decision.
  Keyboard Enter/Space still activates on the node itself.

The last point is easy to regress and was briefly invisible to the tests, because a test
that dispatches a synthetic `click` at the node exercises a path a real browser can't take
once capture is held. `memory-graph.test.tsx` therefore asserts activation from the
pointer sequence alone, with no `click` event anywhere in it.

## The arrangement persists, per room, in `localStorage`

An arrangement survives a reload, keyed per room under `mycelium.graph.layout.{room}` —
the same shelf and naming the command palette's recents use (`lib/commands.ts`). It's
**local, not hub state**: how you like a graph laid out is a personal view preference, and
pushing it to `.mycelium/` would make one member's arrangement everyone's.

Three rules keep it from rotting, all in `lib/memory-graph-placements.ts` so they're
testable without rendering an SVG:

- **Pruned on read.** Positions are filtered to the keys actually in the current payload,
  and the pruned map is what gets written back. A renamed or deleted memory therefore
  drops its position on the next visit instead of accumulating forever — which was the
  open question that kept this out of the first cut.
- **Versioned, and discarded rather than migrated.** A payload not stamped `v: 1` is
  ignored. The cost of getting this wrong is one drag, so a migration path would be more
  machinery than the data is worth.
- **Every failure degrades to "no arrangement."** Bad JSON, a non-finite coordinate, a
  full or blocked store, or a `localStorage` whose methods are missing entirely — each
  yields an empty map or a skipped write, never a throw. That last case isn't
  hypothetical: this repo's local jsdom hands back exactly such an object, which is why
  the `try`/`catch` here is load-bearing and a `typeof localStorage === "undefined"` guard
  alone would not be.

Hydration happens in an effect rather than during render, since the server has no
`localStorage` and reading it inline would desync the SSR markup — and specifically in a
**layout** effect, so the saved positions are in place before the first paint. With a
plain `useEffect` the nodes paint at their force-layout positions and jump to the saved
arrangement a frame later, which reads as a flinch on every load. That's safe here only
because `MemoryGraph` never server-renders: `MemoryGraphView` holds `graph` at `null` and
fills it from a fetch, so the server always renders the skeleton instead.

"Reset layout" clears the entry outright instead of storing an empty record.

Writes are debounced by 250ms, because a drag sets the position map on *every*
pointermove and `localStorage.setItem` is synchronous — persisting naively would turn one
gesture into a hundred blocking writes. The debounce is paired with a flush on unmount, so
arranging a graph and immediately navigating away still saves rather than losing the
pending timer.

**Only a drag or a reset may write**, tracked by a `dirty` ref, and this is the subtle
part. The obvious implementation — persist whenever `placed` changes, mirroring state
outward — is broken under `StrictMode`, which Next's App Router enables by default. Its
mount pass runs setup, then *cleanup*, then setup again; that cleanup fired the unmount
flush while `placed` was still the pre-hydration empty map, storing it over the real
arrangement, and the second setup then hydrated from what it had just erased. The symptom
was persistence that worked in every test and never once in the browser. Guarding on
`dirty` fixes it at the root: hydration came *from* the store, so writing it back was
never meaningful work in the first place.

That leaves pruning with no writer, since the user didn't do it — so `loadPlacements`
writes the pruned map back itself, at the one moment it knows an entry became
unreachable.

Both this and the drag interaction are mount-ordering bugs invisible to a bare `render`,
so `memory-graph.test.tsx` wraps *every* case in `StrictMode`, and
`memory-graph-view.test.tsx` covers a full arrange-reload-restore against the real
component tree, where the payload only arrives after a fetch resolves.

## Empty states are two different facts

`fetchMemoryGraph` degrades to `{nodes: [], edges: []}` both for an unreachable hub and
for a room whose link index has never been built (memories written straight to disk stay
unindexed until `mycelium memory reindex`). An empty payload therefore cannot be reported
as "no memories" — the Memory rail sitting beside it may well be listing dozens. The view
says "No link graph for this room" and names the reindex, keeping to what the payload
actually proves.

## Implementation

| File | Role |
| --- | --- |
| `lib/api.ts` (`fetchMemoryGraph`) | Reads `GET /rooms/{room}/links/graph` — nodes with `inbound`/`outbound` counts, edges with `kind`/`relation`/`resolved`. Already existed on the backend (`app/services/links.py:graph`); no backend changes needed. |
| `lib/memory-graph-layout.ts` | Pure `computeForceLayout(graph, options)` wrapping `d3-force`; returns node positions and only the edges that got positioned. |
| `components/memory-graph.tsx` | The SVG canvas: namespace-colored nodes sized by degree, orphan ring (`inbound === 0`), edges solid for links / dashed for relations / red dashed for broken, hover-to-highlight neighbors, wheel-zoom, drag-to-pan, drag-to-arrange with reset, a floating legend, and a summary strip derived from the same payload (no second integrity fetch). |
| `components/memory-graph-view.tsx` | Fetches the graph, handles loading/empty states, and opens a clicked node in a `DetailDrawer` + `MemoryDetail` over the canvas. |
| `app/room/[name]/graph/page.tsx` | The route: `AppShell` + `MemoryGraphView`, under a header mirroring the room page's (same height, room name, actor picker) plus a back link, so the graph reads as a surface *of* the room. |
| `components/memory-panel.tsx` | A "Graph" entry point in the Memory tab's stats row, linking to `memoryGraphHref(roomName)`. |

## One vocabulary for the four ways a link fails

`_resolve` can fail four distinct ways — `not_found`, `no_anchor`, `not_expandable`, and
`cross_room` — and an earlier cut of this view reported all of them as a single "N broken
links", with the raw code in the edge tooltip. Two different things were wrong with that.

The naming is now shared rather than duplicated. `LINK_ERRORS` moved out of
`memory-detail.tsx` into `lib/memory-links.ts` (the home #677 established for exactly this
kind of link vocabulary), so an edge tooltip and a detail-view row phrase the same failure
identically — "no such section", not `no_anchor`. This was deferred until #677 landed
precisely to avoid extracting a constant out of a file that PR was rewriting.

**`cross_room` is counted apart from breakage**, via `isBrokenLinkError`. A
`myc://rooms/other/key` reference is documented, legitimate syntax that simply can't
resolve room-locally; folding it into "broken links" reports a room as damaged for doing
something correct. The strip now says "N broken links" for the three real defects and "N
cross-room" beside it, in muted rather than red.

## Checklist

- [x] `fetchMemoryGraph` reads the existing `/links/graph` endpoint, degrading to
      `{nodes: [], edges: []}` on failure
- [x] `computeForceLayout` places every node at a finite coordinate, and drops
      self-referencing / out-of-graph edges rather than crashing `d3-force`'s link force
- [x] `<MemoryGraph>` colors nodes by top-level namespace, rings orphans, and draws
      solid for links, dashed for relations, red dashed for a broken link whose two ends
      are both real memories
- [x] Clicking a node opens it in the right-hand drawer over the graph, keeping pan, zoom
      and layout; hovering highlights its neighbors and dims the rest
- [x] Nodes can be dragged into an arrangement, edges stay attached, a drag never opens
      the drawer, and "Reset layout" restores the force positions
- [x] The arrangement survives a reload per room, is pruned to memories that still exist,
      and degrades to no-arrangement on any storage failure
- [x] Pan (drag) and zoom (wheel, anchored under the cursor) work on the canvas, with the
      wheel listener bound natively so `preventDefault` actually takes
- [x] A "Graph" link in the Memory tab's stats row opens `/room/{room}/graph`
- [x] Link failures are phrased with the shared `LINK_ERRORS` vocabulary, and a
      `cross_room` reference is counted apart from a genuine break
- [x] An empty payload reports a missing link graph, never "no memories"
- [x] Node buttons stay reachable by keyboard *and* by assistive tech (`role="group"`)
- [x] `package-lock.json` carries `d3-force` — CI installs with `npm ci`, so a pnpm-only
      dependency add fails the build
- [ ] Manual QA: open the graph on a room with orphans and a broken link, confirm the
      summary strip and legend match what the rail already reports for the same room

## Manual QA without a backend

`atlas-migration`'s fixture (`mocks/fixtures.ts`) now carries a hand-authored link
graph — three wikilinks, one `depends-on` relation, and one deliberately broken
wikilink to a non-memory (`plan/tasks`) — so the graph, its summary strip, and the
rail's outbound/backlink panel (`GET /links?key=`) all render real content with
**no SLIM node, no LLM, no docker stack**:

```bash
cd mycelium-frontend && pnpm dev:mock
```

Then open `/room/atlas-migration/graph` (or the "Graph" link in the Memory tab's
stats row). Expect: 8 nodes across 4 namespaces (`agents`, `decisions`, `context`,
`status`), 5 orphans (the four `agents/*` manifests plus `context/synthesis`
itself — nothing links *to* the briefing that links out to everything), and 1
broken link reported in the summary strip. Clicking `decisions/cutover` should
return to the room with that memory focused in the rail, whose link panel should
show the same edges (`context/goal` resolved, `plan/tasks` broken).
`src/mocks/handlers.test.ts` pins this shape as an automated regression check.
