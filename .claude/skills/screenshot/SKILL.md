---
name: screenshot
description: Take a screenshot of the running Mycelium app, or of CLI output rendered as a terminal card, or record a short video of a flow with a visible cursor and click/zoom animations. Use when you need to SEE the UI — verifying a frontend change, checking a layout at phone/tablet/desktop widths, driving a multi-step flow and looking at each step, producing an image of a `mycelium` command's output for a doc or PR, or showing a flow in motion. Triggers on "screenshot", "show me the app", "what does it look like", "check the layout", "responsive", "capture the terminal", "record a video", "screen recording", "demo clip", "show it in motion".
---

# Screenshot the app or the CLI

`shotkit/` is this repo's camera. It holds a browser open in a background
daemon, so the first shot costs ~2s and every later one ~150ms.

Run it from the repo root:

```bash
node shotkit/bin/shot.mjs <command> [flags]
```

The absolute PNG path is the only thing on stdout — read that file back to see
the result. Timings and warnings go to stderr.

## First run on a machine

```bash
node shotkit/bin/shot.mjs doctor
```

It reports the browser, `script(1)`, whether the frontend's deps are installed,
whether an app is already listening, and whether webfonts load here. Fix
anything it marks `✗` before capturing. Terminal and code cards need no app at
all.

**If the webfont check warns, add `--offline` to every app capture** and don't
publish shots taken on this machine — they will render in fallback fonts. A
capture that takes more than a few seconds prints the same hint.

## Screenshot the app

```bash
# boot the mock frontend (no backend, SLIM or LLM needed) and shoot a route
node shotkit/bin/shot.mjs app /room/atlas-migration --mock

# against an app you already have running
node shotkit/bin/shot.mjs app / --base-url http://localhost:3000
```

`--mock` boots `pnpm dev:mock` **inside the daemon**, so it stays warm across
shots — pass it on the first capture and omit it afterwards. An already-running
dev server is found automatically, whatever port it is on.

**Add `--offline` when a capture takes more than a few seconds.** The frontend
links Google Fonts; where those are unreachable, each navigation waits ~13s on
them. `--offline` resolves nothing but localhost and the app renders with
fallback fonts.

## Check a layout across breakpoints

```bash
node shotkit/bin/shot.mjs app / --responsive --sheet --offline
```

Four frames — phone, tablet, laptop, wide — plus one contact sheet composing
them at their true relative widths. Read the sheet: it answers "is this
responsive" in a single look. `--viewports phone,wide` picks a subset;
`--viewport 1280x800@2` takes an exact size.

## Drive a flow, then look

For a state behind a click, either pass ordered steps to one capture:

```bash
node shotkit/bin/shot.mjs app /room/atlas-migration --offline \
  --do click:Negotiate --do wait:.offer-grid
```

…or hold the page open and work against it, which is what you want when you
need to see each step before deciding the next:

```bash
node shotkit/bin/shot.mjs open /room/atlas-migration --session r --offline
node shotkit/bin/shot.mjs do click:Negotiate --session r
node shotkit/bin/shot.mjs shoot --session r --name negotiate   # ~250ms
node shotkit/bin/shot.mjs close --session r
```

A bare word (`click:Negotiate`) matches an accessible name, then visible text —
including words that are also tag names, so `click:table` finds a button
labelled "table" before it considers a `<table>`. For anything else use a
Playwright selector: `#id`, `.class`, `role=button[name="Save"]`, `text=Save`.
`shot help shoot` lists every verb.

## Record a short video

When the thing to show is a *flow* rather than a state — a demo clip for a PR or
a doc, or checking that an interaction feels right:

```bash
node shotkit/bin/shot.mjs video /room/atlas-migration --mock --offline \
  --do click:Negotiate --do wait:.offer-grid --auto-zoom
```

Same `--do` verbs as a screenshot. The recording adds what a still does not
need: the pointer travels to each target (moving the real mouse, so hover states
fire), a ring marks each click, and `--auto-zoom` pushes the camera in on what is
being pressed and back out after. `zoom:<sel>`, `zoom:<sel>@2.2` and `zoomout`
place the camera by hand.

The output path on stdout is an **.mp4 where the machine has a full ffmpeg, and
a .webm otherwise** — Playwright's bundled build is webm-only. `shot doctor`
says which. You cannot watch it: hand the path to the user, or pull a frame out
of it to look at. Keep takes short (a few actions); `--max-seconds` caps one.

## Screenshot CLI output

Runs the command under a pty, so Rich keeps its colors and box drawing:

```bash
node shotkit/bin/shot.mjs term --cols 84 -- mycelium memory --help

# run one command, label it as another (the CLI often needs `uv run` locally)
node shotkit/bin/shot.mjs term --cwd mycelium-cli --command "mycelium doctor" \
  -- uv run mycelium doctor
```

Flags must come **before** the command; everything after the first plain word
belongs to the child. `shot text <file>` renders an ANSI log you already have,
and `shot code <file> --range 40:80` makes a syntax-highlighted code card.

## Framing for a PR or doc

```bash
node shotkit/bin/shot.mjs app /room/atlas --chrome --offline          # browser window frame
node shotkit/bin/shot.mjs app / --chrome --theme light --backdrop dusk
node shotkit/bin/shot.mjs app / --chrome --backdrop mycelial --padding 90
```

`--theme` switches the app itself, not just the browser's media query.

`--backdrop mycelial` is the desktop behind the window: the docs site's own
mycelial network, the same one `docs/banner.png` is cut from. Give it padding to
show — and prefer a quiet backdrop (`mycelium`, `ink`, `paper`) when the screen
itself is busy.

## Rules

- **Never commit anything from `.shotkit/`.** It is gitignored scratch. The
  committed docs screenshots have their own pipeline — `pnpm screenshots` in
  `mycelium-frontend/`, publishing per `screenshots/targets.ts`. Run that, and
  commit its output, only when asked to update the docs assets.
- **Don't hand-roll Playwright for a screenshot.** If shotkit is missing a
  capability, add it there; `capture()` in `shotkit/src/api.mjs` is importable.
- **Leave the daemon running.** It idles out after 15 minutes. `shot stop` only
  if you need a clean slate.
