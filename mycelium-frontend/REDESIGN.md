# UI redesign brief

> Status: critique + direction. Not a spec yet — this exists to get everyone
> looking at the same problems in the same words before we touch components.

## Thesis

Every element in the app is wearing a **terminal costume**: uppercase monospace
labels, square status dots, hairline borders, and saturated cyan/green — applied
*uniformly*, as decoration rather than hierarchy. That aesthetic reads as "sharp
systems tool" briefly, then reads as dated/goofy, because novelty texture ages
fast and real hierarchy doesn't.

A telemetry screen (metrics, the L9 inspector) can wear that costume honestly. A
**conversation** cannot — which is why the room chat feels the most wrong. Human
dialogue is being rendered in the same monospace-telemetry skin as protocol frames.

This is not deep rot. It's ~6 repeated patterns applied too broadly. And the fix
has a head start: the shadcn semantic-token bridge already exists
(`src/app/globals.css:176-200`) — it's just sitting unused under a custom palette.

## Principle: register, not uniformity

The app has two registers and should stop pretending they're one:

- **System register** (mono, tabular, dense, cyan-tinted): IDs, timestamps, metrics,
  code, L9 frames, episode URNs. The costume is *correct* here.
- **Human register** (sans, sentence case, roomy, neutral): conversation, room
  names, section headings, buttons, empty states, dialogs.

Almost every taste complaint is a human-register surface wearing system-register
clothes. The redesign is mostly moving things into the right register.

## The six problems

### 1. Monospace maximalism
`.caps-mono` / `.caps-mono-sm` is the *default* label style — nav tabs, section
headers, buttons, the "SEND AS" field, agent counts, breadcrumbs (~50+ usages).
Monospace is a signal for tabular/system data; spending it everywhere flattens the
whole product into one undifferentiated terminal readout.

**Direction:** mono earns its place only in the system register (IDs, timestamps,
metrics, code, L9). Everything human → IBM Plex Sans, sentence case. Keep the serif
wordmark. Retire `caps-mono` as a general-purpose label.

- Offenders: `main-top-bar.tsx` (nav), `sub-nav.tsx` (breadcrumb), `room-chat-box.tsx`
  (labels + button + textarea), `agents-panel.tsx` / `episodes-rail.tsx` (headers),
  `page.tsx` (table headers).

### 2. No color system — accent-splatter
One cyan (`#5dd4e0`) does ~6 unrelated jobs (nav-active, buttons, links, focus ring,
@-mentions, live dots), alongside hardcoded green/yellow (and an unused purple). ~49
inline `style={{ color: "var(--…)" }}`. Because these saturated hues sit *directly*
on near-black with no tonal midground, they read as garish.

**Direction:** adopt a disciplined semantic palette (shadcn neutral base + one accent).
Accent gets exactly one job: primary action + active state. Status flows through
`muted`/`foreground`, with green/yellow reserved for *true* semantic state
(converged / rejected / error) — not general emphasis. Eliminate inline color styles
in favor of tokens.

- Source: `globals.css:4-51` (the custom onyx palette, duplicated across `@theme`
  and `:root`).

### 3. The memory rail is a gimmick
The right rail collapses to a 9px spine with vertically-rotated text
(`writingMode: vertical-lr`, `collapsible-rail.tsx:51`). It's hard to click, hard to
read, and matches nothing else in the UI. This is the single most "goofy" element.

**Direction:** a normal collapsible panel (shadcn `Sheet`, or a plain bordered panel
with a horizontal header + a standard toggle button). Horizontal label. Real hit target.

### 4. The chat box isn't a chat surface
Two problems, one perception:
- **The stream reads like a log**, not a conversation: every message is a full-width
  row with a `border-b` divider and a bordered avatar (`event-stream.tsx:533`).
- **The composer reads like a form**, not a chat input: a `SEND AS [handle]` labeled
  mono field, a 2-row bordered textarea, and a bordered uppercase `SEND` button
  (`room-chat-box.tsx:145-223`).

**Direction:** group consecutive messages by sender (avatar + name once per group, no
per-message rules), give the stream breathing room, and rebuild the composer as a
single rounded surface with the send affordance inline. Demote "send as" to a quiet
selector (it's a power-user control, not a headline field).

### 5. No theming
`<html class="dark">` is hardcoded (`layout.tsx`), there's no `next-themes`, and the
palette is duplicated across `@theme` and `:root` — two sources of truth that will
drift.

**Direction:** consolidate onto the shadcn CSS-variable contract as the single source
of truth, add `next-themes`, and define both a dark and a light token set. This isn't
just "add light mode" — committing to the token contract is what *forces* the color
discipline in #2.

### 6. Custom re-inventions of shadcn
`create-room-dialog.tsx` is a hand-rolled modal even though `ui/dialog.tsx` exists;
`ui/chip.tsx` is bespoke; there are many one-off bordered boxes. This is the "goofy
custom shit" — more surface to maintain, inconsistent behavior.

**Direction:** standardize on the `ui/*` primitives (they're already shadcn/base-ui
wrappers). Route `create-room-dialog` through `ui/dialog`. Fold `Chip` into a shared
badge. Delete one-offs.

## What to keep

The redesign is subtractive, not a rebrand. Keep:
- The serif italic **mycelium** wordmark (the one place the costume earns contrast).
- The **information architecture**: left rail (agents + episodes), center chat,
  right memory, CHANNEL / L9 / PLAN tabs. The layout is right; the skin is wrong.
- The **system register** itself — the L9 inspector and metrics screen *should* stay
  mono/dense/tabular. Don't sand those down.

## Suggested sequencing

Ordered so each step de-risks the next; each is independently shippable.

1. **Theming foundation (#5 + #2):** collapse to one token source, wire `next-themes`,
   define the neutral+accent palette. Nothing visual changes yet — this is the
   substrate everything else pulls from.
2. **Register cleanup (#1):** move human surfaces off `caps-mono` to sans/sentence case.
   Biggest perceived-freshness win for the least structural risk.
3. **Chat surface (#4):** the highest-value single screen — message grouping + composer.
4. **Memory rail (#3):** replace the vertical spine with a standard panel.
5. **Primitive consolidation (#6):** sweep custom components onto `ui/*`, delete one-offs.

Every state is reachable with `pnpm dev:mock` (see `src/mocks/README.md`) —
`/room/atlas-migration` (populated), `/room/pricing-model` (live), `/room/scratch`
(empty), `/metrics`. Design and check against all three room states, not just one.
