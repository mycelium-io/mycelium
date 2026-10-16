<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- Copyright 2026 Mycelium Contributors -->

# Screenshots — the app's camera

Committed PNGs of the real frontend, for the docs site (`docs/`) and the splash
repo (`mycelium-io.github.io/`). Conceptually a sibling of `docs/generate_docs.py`:
both regenerate published artifacts from a source of truth. This one's source of
truth is the UI itself, captured in **mock mode** (`pnpm dev:mock`,
`MYCELIUM_UI_MOCK=1`) so every state renders with no backend, SLIM node, or LLM.

```
pnpm screenshots            # boot dev:mock, capture every shot, write PNGs
pnpm screenshots room-board  # a subset, by shot id
pnpm screenshots --keep     # attach to a dev:mock already running on $PORT
pnpm screenshots --offline  # don't wait on webfont CDNs (much faster if they're unreachable)
```

Outputs are **committed** so normal docs/splash builds never need a browser, and
the splash repo builds standalone. Re-run and commit when the UI changes.

## Layout

- **`shots.ts`** — the manifest: every published image as `{ id, route, theme,
  viewport, waitFor?, clip? }`. Adding a shot is an edit here.
- **`targets.ts`** — where each shot's PNG(s) land (docs/ and/or splash), and the
  `@2x` retina variants. The splash path defaults to a sibling checkout; override
  with `MYCELIUM_SPLASH_DIR`.
- **`capture.ts`** — maps each manifest entry to a `shotkit` spec, then optimizes
  with `sharp` and `optimize.ts` and fans out to targets. The browser work — booting the mock
  server, finding a usable Chromium, waiting for a *populated* frame (shell
  mounted, skeletons cleared, SSE "Live", fonts loaded), driving the page —
  belongs to `shotkit/`, the repo's screenshot utility, because it is the same
  problem whether the caller is this pipeline or an agent at a terminal. What
  stays here is publication's business: which shots exist, how they're
  optimized, and where they land.

- **`optimize.ts`** — lossless oxipng (WebAssembly, no system install) over
  every PNG written. CI fails a committed PNG oxipng could still shrink by more
  than 10%; for an image made some other way, `npm run optimize-png -- <file>`.

## Adding a shot

1. Add an entry to `SHOTS` in `shots.ts` (route + theme + viewport).
2. Map it to output paths in `TARGETS` in `targets.ts`.
3. If `pnpm dev:mock` can't render that state, add/extend a fixture in
   `src/mocks/fixtures.ts` first — the pipeline can only shoot what the mock can
   render. Interactive states (an open `@`/`[[`/`/` composer popover) are reached
   with `steps`, which become shotkit actions, not with a fixture.
4. `pnpm screenshots <id>` and eyeball the result.

## The home page's wake note

One picture on the home page isn't the app: `step-wake-agent`, the note an
agent reads when it wakes. It is a terminal card of `wake-note.txt`, a sample
wake for `builder` in the mock's `checkout` room, written in the format
`fastapi-backend/app/services/wake_digest.py` builds. When that format changes,
update the text to match and remake the card from the repo root:

```
node shotkit/bin/shot.mjs term --cols 100 --backdrop none --padding 0 \
  --title "builder · claude" --command "the wake @builder reads" \
  -o ../mycelium-io.github.io/step-wake-agent@2x.png \
  -- fold -s -w 100 mycelium-frontend/screenshots/wake-note.txt
```

`fold` wraps the long lines the way a terminal would; without it the card
widens to the longest line and its text shrinks on the page. Then make
`step-wake-agent.png` at half that width (on a Mac,
`sips -Z <half> step-wake-agent@2x.png --out step-wake-agent.png`) and run
`npm run optimize-png -- <file>` on both, in `mycelium-frontend`.

## Notes

- Needs a Chromium; `node ../shotkit/bin/shot.mjs doctor` says whether one is
  usable and how to get one.
- Waits gate on content, never timeouts — deterministic fixtures mean no flake.
- To iterate on a single shot interactively, `shot app <route> --mock` is the
  faster loop: it holds the browser and the dev server open between captures.
