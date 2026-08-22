<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- Copyright 2026 Mycelium Contributors -->

# shotkit — the repo's camera

Screenshots of the running app, and of CLI output, fast enough to take one
mid-thought. Built for coding agents first: one line in, an absolute PNG path
out, ready to read back.

```bash
shot term mycelium memory ls --room atlas     # a terminal card, real ANSI colors
shot app /room/atlas-migration --mock         # the running frontend
shot app / --responsive --sheet               # every breakpoint in one image
shot code src/services/aligner.py --range 40:80
```

Nothing here is on the install path or in the runtime. A user never executes it.

## Why it is fast

A screenshot script that launches a browser per invocation spends about two
seconds doing the same three things every time. shotkit pays them once:

| | |
|---|---|
| **A daemon holds the browser.** | First shot ~2s, every later shot ~150ms. It starts itself, and shuts down after 15 idle minutes. |
| **Cards never touch the network.** | `term`, `code` and `html` render a self-contained document into a page that stays open. No navigation, no fetches. |
| **`--mock` boots the app once.** | The Next dev server is held by the daemon, not by the request, so six shots of six routes boot it once. |
| **`--offline` skips dead CDNs.** | The frontend links Google Fonts. Where those are unreachable, waiting on them costs ~13s *per navigation* — more than everything else combined. |

```
$ shot bench
cold (no daemon, includes browser launch): 2142ms
warm x6: min 134ms · median 163ms · max 486ms
speedup: 13.1x
```

## The commands

| | |
|---|---|
| `shot app [route]` | the running frontend; `--mock` boots `pnpm dev:mock` |
| `shot url <url>` | any URL |
| `shot term <command…>` | run a command, shoot its terminal output |
| `shot text <file\|->` | render an existing ANSI capture |
| `shot code <file>` | a syntax-highlighted code card |
| `shot html <file\|->` | render an HTML document |
| `shot open` / `do` / `shoot` / `close` | drive a page held open — see **Navigation** |
| `shot warm` / `status` / `stop` / `serve` | the daemon |
| `shot doctor` / `bench` | check and time this machine |

`--backdrop` takes `mycelial` (the site's network — see **The desktop**),
`mycelium`, `dusk`, `ink`, `paper`, `none`, or any CSS.

`shot help <command>` lists every flag. stdout carries the path and nothing
else, so it composes: `open "$(shot app / --mock)"`.

## Terminal cards

`shot term` runs the command under a pty, so Rich emits exactly what it emits
for a person — color, box drawing, the lot — and the output is replayed through
a small screen buffer before rendering. That replay matters: a spinner redraws
with `\r` and a Live region repaints by moving the cursor up, and concatenating
the raw stream would stack every intermediate frame into one image. What you get
is the terminal as you would have found it.

```bash
shot term --cols 84 --title mycelium -- mycelium memory --help
shot term --command "mycelium doctor" -- uv run mycelium doctor   # run one thing, show another
shot text ci-failure.log --window plain                           # a capture you already have
```

Colors come from the frontend's own palette, so a terminal card and an app
screenshot sit next to each other without clashing.

## Responsive

```bash
shot app / --responsive --sheet          # phone, tablet, laptop, wide + one contact sheet
shot app / --viewports phone,wide
shot app / --viewport 1280x800@2
```

The contact sheet composes the frames at their true relative widths — a phone
beside a 1920 monitor reads as a phone — so checking a layout is one image to
look at rather than four.

## Navigation

A one-shot capture takes ordered steps:

```bash
shot app /room/atlas --do click:Negotiate --do wait:.offer-grid --do scroll:bottom
```

For anything longer, hold the page open. The daemon keeps it under a name, so
you can look, decide, and act, without replaying the flow from a cold load each
time — and each shot is ~250ms.

```bash
shot open /room/atlas --session r --viewport laptop
shot do click:Negotiate --session r
shot shoot --session r --name negotiate
shot shoot click:Plan sleep:300 --session r --name plan   # act and shoot in one call
shot sessions ; shot close --session r
```

Element arguments accept any Playwright selector engine (`text=`,
`role=button[name="Save"]`, `#id`, `//xpath`). A bare word is matched by
accessible name, then by visible text — `click:Save` means the button labelled
Save, not a `<save>` element.

## Browser chrome

`--chrome` re-renders a page capture inside the same window frame the terminal
cards use, with an address bar:

```bash
shot app /room/atlas --chrome --backdrop dusk
shot app / --chrome --theme light                 # app and frame both light
shot app / --chrome --theme dark --chrome-theme light
```

`--theme` drives the app's own theme, not just the browser's `prefers-color-scheme`:
next-themes reads `localStorage` before first paint and would otherwise ignore it.

## The desktop

`--backdrop mycelial` puts the docs site's own hypha network behind the window,
so a framed screenshot sits on the product's background rather than a gradient:

```bash
shot app /room/atlas --chrome --backdrop mycelial --padding 90
shot term --backdrop mycelial -- mycelium memory ls --room atlas
```

It is the same network in both senses. The algorithm is the one the live site
runs — read from `scripts/banner-assets/mycelial-canvas.js`, the copy
`docs/banner.png` is already cut from, rather than a third transcription of it
— and the colors are the site's `--canvas-*` values, cream and quiet in light,
near-black and teal in dark.

A vignette in the ground's own color veils it, lightly in the middle and
heavily at the edges. The site can run the network at full strength because
prose sits on near-solid paper above it; a screenshot has no such pane, and an
unveiled network pulls the eye into the corners and away from the window. Light
is veiled less than dark, since the site already runs it quieter.

One network is grown per theme and held for the life of the daemon, so a run of
shots shares one desktop and only the first pays to grow it — about 150ms once,
after which a framed shot costs what any other does. It grows from a fixed seed,
so the same command gives the same background tomorrow and a committed asset
does not churn on every re-render; `--backdrop-seed <n>` asks for a different
one.

The other backdrops (`mycelium`, `dusk`, `ink`, `paper`, `none`, or any CSS you
pass) are unchanged, and are what to reach for when a shot wants quiet behind
it: the network is texture, and texture competes with a busy screen.

## The library

```js
import { capture } from "../shotkit/src/api.mjs";

const r = await capture({ op: "app", route: "/", responsive: true, sheet: true });
r.path;      // absolute path of the sheet
r.shots;     // one entry per breakpoint
```

`mycelium-frontend/screenshots/capture.ts` is the other consumer: it publishes
the committed docs assets and uses this engine for the browser work, keeping
only what is publication's business — the shot manifest, the `sharp` pass, and
where files land.

## Notes

- **macOS and Linux.** Both need `script(1)` (present by default) for terminal
  cards, and a Chromium. `shot doctor` says what is missing.
- **Any Chromium will do.** Playwright pins an exact build and refuses others;
  shotkit falls back to `executablePath` for whatever is on disk, so a version
  skew between the driver and the host's browser is not a re-download.
- **Editing shotkit restarts the daemon.** It stamps its own source at boot and
  the client replaces it when that moves, so a fix never silently runs stale.
- **Captures land in `.shotkit/`** (gitignored) and overwrite by name; `--unique`
  timestamps instead.
