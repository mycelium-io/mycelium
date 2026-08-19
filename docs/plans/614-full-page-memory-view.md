# #614 — Full-page memory view

Branch: `614-full-page-memory-view`  
Issue: [https://github.com/mycelium-io/mycelium/issues/614](https://github.com/mycelium-io/mycelium/issues/614)  
Epic: #600 (interlinked wiki). Complements #599 (graph UI). Builds on #611 (linking, merged).

## Problem

Memory content lives in the right-rail inspector (~340px drawer). For an interlinked
wiki (#600), reading a page, walking wikilinks, expanding transclusions, and scanning
backlinks all fight for that width. Chat wikilinks (#611) land in the rail; the content
deserves a real page.

## Goal

Dedicated, deep-linkable wiki page at `/room/{room}/memory/{key}` (URL-encoded key,
slashes allowed). Rail stays as **quick peek**; full-page is the reading surface.

## Non-goals

- Graph **visualization** (#599) — force-directed graph, link autocomplete in editor
- Frontmatter schema editing (#596)
- Cross-room link resolution (surface `cross_room` errors as-is)
- Mandatory chat wikilink → full page (#614 says that promotion is **optional**)

## Related issues


| Issue | Role                                                                        |
| ----- | --------------------------------------------------------------------------- |
| #600  | Epic — #614 is the dedicated-route track                                    |
| #611  | Merged — wikilinks, backlinks, relations in rail; transclusion markers only |
| #599  | Graph viz + global inline transclusion in `markdown-content` (later)        |
| #596  | Frontmatter schemas (out of scope)                                          |


#599's open question (*rail vs full-page*) is answered here: **full-page for reading**;
graph stays in Memory area (#599).

---

## Implementation phases (with tests)

Each phase ships with unit tests that prove the intended behavior, or documents deferred
tests when the slice needs a later phase.

### Phase 1 — Routing & URL helpers

**Deliverables**

- `src/lib/memory-routes.ts` — `encodeMemoryKeyPath`, `parseMemoryKeyParam`, `memoryHref`
- `src/app/room/[name]/memory/[...key]/page.tsx` — catch-all route
- `fetchMemory` uses shared encode helper

**Tests (**`memory-routes.test.ts`**)**

- Round-trip keys with slashes and special chars
- `memoryHref("demo", "decisions/db")` → `/room/demo/memory/decisions/db`
- Room names with spaces are encoded

**Deferred until Phase 2**

- Page integration test (needs `MemoryPageView`)

---

### Phase 2 — Full-page view component

**Deliverables**

- `src/components/memory-page-view.tsx` — loads memory, expand, integrity; renders layout
- Reuse `MemoryDetail` with `variant="page"`

**Tests (**`memory-page-view.test.tsx` **or** `memory-detail.test.tsx`**)**

- Renders memory key and body when props/data provided
- Shows neighbors section (1-hop from links API)
- Shows integrity note when memory has broken outbound or is orphan
- Rendered mode uses expanded body when expand API returns content

---

### Phase 3 — Rail affordances

**Deliverables**

- "Open full page" link in `DetailDrawer` header (memory panel)
- `navigateToKey`: if key not in loaded list → `router.push(memoryHref(...))`

**Tests**

- `memory-detail.test.tsx`: "Open full page" href correct when `showOpenFullPage`
- `memory-routes.test.ts` already covers href generation (panel uses same helper)

---

### Phase 4 — Navigation & search

**Deliverables**

- `resultHref` for `memory` hits → direct memory URL (not `?focus=`)
- Room page: legacy `?focus=memory:…` redirects to memory URL
- Chat wikilink → rail unchanged (#614 optional); document as follow-up

**Tests (**`search.test.ts`**)**

- Memory hit href is `/room/{room}/memory/{encoded-key}`
- Room hits unchanged
- Legacy focus parse still works for non-memory types

---

### Phase 5 — API clients & link surfaces

**Deliverables**

- `fetchMemoryExpanded`, `fetchMemoryIntegrity` in `api.ts`
- `src/lib/memory-links.ts` — `neighborKeys()`, `integrityNotesForMemory()` (pure)

**Tests (**`memory-links.test.ts`**)**

- Neighbors = unique outbound targets + backlink sources (excluding self)
- Integrity notes for broken outbound from this key and orphan status

---

## File checklist


| Action | File                                                   |
| ------ | ------------------------------------------------------ |
| Add    | `src/lib/memory-routes.ts`, `memory-routes.test.ts`    |
| Add    | `src/lib/memory-links.ts`, `memory-links.test.ts`      |
| Add    | `src/app/room/[name]/memory/[...key]/page.tsx`         |
| Add    | `src/components/memory-page-view.tsx`                  |
| Add    | `src/components/memory-detail.test.tsx`                |
| Edit   | `src/lib/api.ts`                                       |
| Edit   | `src/components/memory-detail.tsx`                     |
| Edit   | `src/components/memory-panel.tsx`                      |
| Edit   | `src/lib/search.ts`, `search.test.ts`                  |
| Edit   | `src/app/room/[name]/page.tsx` (legacy focus redirect) |


---

## Manual test checklist (demo room)

Open this file in the editor and click the boxes as you go (`- [ ]` → `- [x]`).

### Prerequisites

- [x] Backend healthy: `curl http://localhost:8000/health` returns `"status":"ok"`
- [x] Frontend at [http://localhost:3000](http://localhost:3000) (`pnpm dev` in `mycelium-frontend`, or dev container)
- [x] Demo room has interlinked memories (`context/overview`, `decisions/db`, etc.)

### 1. Direct URL — full-page load

- [x] Open [http://localhost:3000/room/demo/memory/context/overview](http://localhost:3000/room/demo/memory/context/overview)
- [x] Page uses full width (not the ~340px rail drawer)
- [x] Header shows room back link and memory key title
- [x] Memory body renders (markdown, wikilinks clickable)
- [x] **Related** section lists 1-hop neighbors

### 2. Wikilink navigation on full page

- [x] Click a `[[wikilink]]` in the body (e.g. `decisions/db`)
- [x] URL updates to `/room/demo/memory/decisions/db`
- [x] New memory content loads correctly

### 3. Transclusion (Rendered mode)

- [x] On a memory with `![[key]]`, **Rendered** mode is default
- [x] Expanded content appears (not raw `![[…]]` markers)
- [x] **Raw** toggle shows original markdown
- [x] Back to **Rendered** restores expanded view

### 4. Integrity banner

Demo pages (seeded in `demo`):

- [x] **Orphan only:** [http://localhost:3000/room/demo/memory/context/integrity-orphan](http://localhost:3000/room/demo/memory/context/integrity-orphan) → `nothing links here yet (orphan)`
- [x] **Broken outbound only:** [http://localhost:3000/room/demo/memory/context/integrity-broken](http://localhost:3000/room/demo/memory/context/integrity-broken) → `2 broken outbound links`
- [x] **Both:** [http://localhost:3000/room/demo/memory/context/integrity-both](http://localhost:3000/room/demo/memory/context/integrity-both) → broken outbound · orphan
- [x] Clean memory (e.g. overview) shows no spurious warnings

### 5. Rail → full page

- [x] Open [http://localhost:3000/room/demo](http://localhost:3000/room/demo)
- [x] Memory tab → select a memory in the rail
- [x] Drawer header **Full page** link (title: "Open full page") is visible
- [x] Click → navigates to `/room/demo/memory/{key}` with same content

### 6. Memory tree vs off-tree navigation

- [x] Memory **in tree** → opens in rail (peek unchanged)
- [x] Key **not in tree** (search or direct URL) → full-page URL *(direct URL path covered by §4 orphan/both pages; search palette is §7)*

### 7. Search → direct memory URL

- [x] Search palette finds a memory (e.g. `overview` or `memory:context`) — open with `**/**` or `**/ search**` in the status bar (not ⌘K)
- [x] After clicking a **memory** row, address bar is `/room/demo/memory/...` (not `?focus=memory:…`) — no copyable link on rows; watch the URL change on click

### 8. Legacy focus redirect

- [x] Open [http://localhost:3000/room/demo?focus=memory:context/overview](http://localhost:3000/room/demo?focus=memory:context/overview)
- [x] URL replaces with `/room/demo/memory/context/overview`
- [x] Full-page view loads

### 9. Missing key

- [x] Open [http://localhost:3000/room/demo/memory/does/not/exist](http://localhost:3000/room/demo/memory/does/not/exist)
- [x] **Memory not found.** with **Back to room** link
- [x] Back link returns to `/room/demo`

### 10. Chat wikilink (unchanged — optional follow-up)

- [x] Click `[[wikilink]]` in chat → memory **rail** opens (not full page)

### 11. Edge cases

- [x] Slashed key loads: `/room/demo/memory/decisions/storage-model`
- [x] Browser back/forward between memory pages works

### Ship (after manual QA)

- [ ] Critical items 1–9 pass
- [ ] Unit tests green: `pnpm exec vitest run src/lib/memory-routes.test.ts src/lib/memory-links.test.ts src/lib/search.test.ts src/components/memory-detail.test.tsx`
- [ ] Commit on `614-full-page-memory-view`
- [ ] Open PR referencing #614

**Quick smoke (~2 min):** 1 → 2 → 5 → 7 → 9