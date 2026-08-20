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
neighbors; filter by namespace or relation; pan and zoom to explore a larger room.

## Non-goals

- A full-page **reading** surface for one memory (`/room/{room}/memory/{key}`) — that's
  #614, landed as #677. This view never depended on it and still doesn't: clicking a node
  opens a drawer over the canvas rather than navigating anywhere.
- Link autocomplete while **authoring** a memory, the one bullet of #599 this doesn't
  touch. It is blocked rather than declined: the frontend has no memory editor at all —
  `MemoryDetail` is read-only and the memory API client has no create or update call — so
  the prerequisite is a memory-authoring surface, which nothing currently tracks. The
  chat composer's `[[` autocomplete (#618) is a different surface and doesn't cover it.
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

## Namespace colors are positional, not hashed

A namespace takes the *nth* palette slot for its position in the room's sorted namespace
list. The first cut hashed the name into the 8 slots instead, which is subtly the wrong
tool: `context` and `decisions` collide on the same slot, so the two namespaces nearly
every room has rendered in the *same* color. That's not a palette that needs retuning —
no choice of 8 colors fixes a collision — so the assignment had to change.

Positional assignment makes a collision impossible below 9 namespaces, and the palette is
therefore ordered **farthest-apart-first** (90°, 235°, 325°, then filling in) rather than
walking the hue wheel, so the two or three namespaces a real room has land 90°+ apart
instead of on three neighboring greens. The ordering lives in the CSS variable list, which
is why that block is commented as load-bearing.

The cost is that a color isn't stable across rooms, and adding a namespace can restripe
the ones sorting after it. That's the right trade here: the legend states the mapping
on screen, so a color only has to be unambiguous *in the room you're looking at*, and
cross-room recognizability was never something this view offered.

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

The drawer is also handed `renderedBody` and `integrity`, the same two things the rail
and the full page pass. Without the first, `![[key]]` renders as an unexpanded chip, so
the *same memory* would read differently depending on which surface you opened it from;
without the second, a memory with a broken link shows no banner here while showing one
everywhere else. Both are the room-wide calls #677 already established —
`fetchMemoryExpanded` per opened key, `fetchMemoryIntegrity` once per room, since the
report covers every memory and `MemoryDetail` slices out the row it needs.

## Filter by namespace and relation

The legend doubles as the filter: each namespace row and each link type is a toggle. A
separate filter control would have to list the namespaces and relations a second time,
and then the two lists could disagree about what an edge is called — so the thing that
*names* the categories is the thing that hides them. A link type is `relation ?? kind`,
the exact string the edge tooltip shows, for the same reason.

Filters are held as the **hidden** sets, not the shown ones, so the unfiltered graph is
the empty state and a namespace that only appears in a later payload isn't silently
excluded for never having been ticked. The link-type section is omitted entirely when a
room has only one kind of edge, since a lone toggle that can only hide everything isn't a
filter.

Filtering never re-runs the layout. Nodes hold their coordinates, so toggling a namespace
off and back on returns the graph exactly as it was rather than reshuffling it — and it
can't fight the saved arrangement, which is keyed per node.

Four rules about what a filter *means*, each of which was wrong in the first cut:

- **Hiding a namespace takes its edges with it.** An edge needs its type shown *and* both
  endpoints visible, or it would be drawn dangling into a node that isn't there.
- **A broken link is a fact about its source.** The count turns on the source alone.
  Requiring a visible target would drop every `not_found` from the tally, because its
  target isn't a memory in this room to begin with — the whole reason it's broken.
- **Orphanhood is a fact about the room.** `inbound` comes from the full graph, so hiding
  a namespace narrows the orphan *tally* to what's shown without reclassifying anything.
  Recomputing it from the visible edges would report a memory as orphaned merely because
  you'd hidden the namespace that links to it.
- **Hover highlighting walks the drawn edges, not the payload.** Neighbors are derived
  from the visible edge set, or hovering would un-dim a memory on the strength of a
  connection the canvas isn't drawing — the one place where reading through the filter is
  right, because the highlight is a claim about what you can see.

The last two look contradictory and aren't: an orphan badge is a claim about the *room*,
so it ignores the filter; a hover highlight is a claim about the *picture*, so it obeys it.

Hovering has one more wrinkle: hiding a namespace unmounts its nodes, and an unmounting
element fires no `mouseleave`, so the hovered key can outlive the node it named. Since
hovering dims everything that isn't a neighbour, a stale key dimmed the *entire* canvas
with nothing highlighted to explain why. A hovered key that is no longer visible therefore
counts as not hovering. It's most easily hit by keyboard — tab to a legend toggle and press
Enter while the cursor still rests on a node.

Every count in the summary strip describes what's on screen, so the strip and the canvas
can't disagree; when a filter is active the memory count says what it's a subset of ("2
memories of 3"). Hiding every namespace says so in the middle of the canvas rather than
leaving a blank rectangle.

Unlike the arrangement, filters are **not** persisted. An arrangement is how you like to
look at a room; a filter is a question you're asking right now, and having one silently
still applied on your next visit would read as missing data.

## Drag to arrange

Nodes can be dragged, and the arrangement is kept in a `Record<key, {x, y}>` that
overrides the force layout per key; a "Reset layout" button appears once anything has
moved. This is cheap *because* the simulation is one-shot: it has already stopped before
anything renders, so a drag is a plain coordinate override with no `fx`/`fy` pinning, no
`alphaTarget` reheating, and no simulation-versus-React ownership to arbitrate. Four
details carry the weight:

- Edges read their endpoints from the live position map. The layout deliberately returns
  *no* edge coordinates at all, so "draw from the frozen position" isn't an option a
  future caller can accidentally take — coordinates baked at the moment the simulation
  stopped would leave a line pointing at where its node used to be.
- A press only becomes a drag past `DRAG_THRESHOLD` (4px), so the tremor in an ordinary
  click doesn't nudge a node.
- Pointer capture is taken on the `<svg>` rather than the node, so a drag survives the
  cursor outrunning the circle it grabbed. It's called optionally, since jsdom doesn't
  implement `setPointerCapture` on SVG elements — and because it's optional, a move
  arriving with no buttons held also ends the gesture. Without capture the release
  outside the canvas is simply never delivered, and the only remaining evidence that it
  happened is that nothing is held down; without acting on it the node would trail the
  cursor forever.
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

## Gestures are measured in graph units, and stepwise

Two conversions are easy to get wrong here, and both were wrong at first.

`view.x/y` feed a `translate()` **inside** the SVG, so they are in the viewBox's user
units — while a pointer event reports client pixels. Since the canvas is `h-full w-full`
over a fixed `1000x700` viewBox, those two units are equal only in a pane that happens to
be exactly that size. Panning by the raw pixel delta therefore made the graph outrun the
cursor in a wide pane and lag it in a narrow one. Everything now converts through
`toSvgPoint` first. Node drags additionally divide by the zoom (nodes live *inside* the
scaled group, so a screen distance is a smaller model distance); pans do not, because
`translate` runs before `scale` and so already speaks parent units.

Each move also applies **the step since the previous move**, not the total since the
press. Measuring from the press means the whole accumulated displacement is re-divided by
whatever the zoom is *now*, so a wheel tick mid-drag retroactively rescales it and the
node visibly snaps. Stepwise, a zoom just changes the scale of what follows.

Both were invisible to the suite for the same reason: the drag tests stub the canvas at
exactly `1000x700`, where one pixel is one unit and every missing conversion cancels out.
There is now a pan test at a deliberately different size, and a zoom-mid-drag test that
dispatches the wheel and the following move in separate `act()`s — in one `act()` the
handler hasn't re-rendered yet, still closes over the old scale, and the assertion passes
against the bug.

## Which presses the canvas answers to

A press is only a gesture if it's `button === 0 && isPrimary`. Without that a right-click
opened the memory *behind* the context menu (a press that doesn't move is exactly how this
view decides a click happened), and a second finger overwrote the single drag slot,
freezing whatever the first one was moving. Declining the extra pointer is the whole of
the multi-touch story — there is no pinch-zoom; the wheel and the zoom buttons are it.

`pointercancel` discards the gesture rather than completing it. Routing it through the
same path as `pointerup` meant a pointer the system took away — a touch handed to a
browser gesture, a device unplugged — opened whatever memory it happened to be over.

Activation also re-checks that the node is still visible, since a filter applied during
the press can retire the node under the finger.

Test fidelity matters more than usual here: `PointerEventInit` defaults `buttons` to `0`
and `isPrimary` to `false`, which is a non-primary pointer with nothing held down — the
exact shape the canvas is built to reject. Synthetic gestures spell both out, or they test
a press no browser sends.

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
- [x] The legend filters: namespaces and link types toggle, hidden namespaces take their
      edges with them, counts follow the visible subset, and one click clears
- [x] The drawer shows transcluded bodies and integrity banners, matching the rail and
      the full-page view
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

## Graph library decision

**Why hand-rolled SVG + d3-force (and when to revisit)**

The implementation uses a custom SVG renderer driven by `d3-force` rather than a
third-party graph component. This was a deliberate choice, not a default.

### What we evaluated (August 2026)

| Library | Renderer | Verdict |
|---------|----------|---------|
| **react-force-graph-2d** | Canvas + d3-force | Closest alternative — same physics, less code, Canvas is faster for 200+ nodes |
| **React Flow (@xyflow/react)** | DOM/SVG | Built for node *editors* (drag-to-connect workflows), not navigation graphs |
| **Sigma.js / @react-sigma** | WebGL | Scales to 100k nodes; customization requires shader work — overkill for room scale |
| **Cytoscape.js** | Canvas | Rich graph-analysis algorithms; heavier than needed for a read-only view |
| **graphier** | Three.js + WebGL + Web Worker | Impressive specs but 62 downloads/week as of evaluation — too early |
| **ReGraph** | WebGL | Commercial (Cambridge Intelligence); not OSS |

### Why we stayed with hand-rolled SVG

The SVG performance cliff (where DOM nodes become visibly slow) sits at roughly
500–1000 nodes. A well-used Mycelium room realistically has 50–300 memories, so we
are well clear of that limit. Staying with SVG gave us:

- **Full visual control** — broken-link dashed-red edges, namespace fill colors, and
  the LINK_ERRORS vocabulary are all expressed as plain JSX, not a library callback API.
- **No SSR workaround** — Canvas-based libraries require a `dynamic(() => import(…),
  { ssr: false })` wrapper in Next.js; SVG renders server-side without ceremony.
- **Zero new dependencies** — `d3-force` was already a transitive dependency.

### When to migrate

The natural trigger is "the graph is visibly sluggish during pan/zoom on a full room."
At that point, **`react-force-graph-2d`** is the cleanest next step:

- Same d3-force physics, same `{ nodes, edges }` data shape.
- Canvas rendering replaces our SVG, removing the DOM-node bottleneck.
- Built-in zoom/pan/drag replaces our pointer-event handling.
- The cost: edge styling (dashed broken links, typed-relation colours) must be
  re-expressed as draw callbacks rather than JSX elements.

Sigma.js / WebGL is a further step if Canvas also becomes a bottleneck, but that
threshold is in the tens of thousands of nodes — not a realistic Mycelium scenario.
