<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- Copyright 2026 Mycelium Contributors -->

# shotkit

Screenshots of a running web app, and of CLI output, fast enough to take one
mid-thought. Built for coding agents first: one line in, an absolute PNG path
out, ready to read back.

```bash
shot term git log --oneline -10               # a terminal card, real ANSI colors
shot app /settings                            # the running frontend
shot app / --responsive --sheet               # every breakpoint in one image
shot code src/server.ts --range 40:80
shot video /settings --do click:Save --auto-zoom   # a short take, cursor and all
```

Originally written as the screenshot tool inside
[mycelium](https://github.com/mycelium-io/mycelium); this repo is the
standalone version, usable from any project.

## Install

```bash
git clone https://github.com/juliarvalenti/shotkit ~/Documents/GitHub/shotkit
cd ~/Documents/GitHub/shotkit && npm install && npm link   # puts `shot` on PATH
shot doctor
```

Node 20.6 or newer. Playwright downloads its browser on first use if no
Chromium is on disk; `shot doctor` says what it found.

### The Claude Code skill

`skills/shotkit/SKILL.md` teaches a coding agent to use `shot`. Link it into
your personal skills so it is available in every project, and stays current
with `git pull`:

```bash
ln -s ~/Documents/GitHub/shotkit/skills/shotkit ~/.claude/skills/shotkit
```

## The project

shotkit works on the project you run it from: the git top-level of the
current directory (or the directory itself outside a repo, or
`SHOTKIT_PROJECT`). Captures land in that project's `.shotkit/` folder, so add
`.shotkit/` to its `.gitignore`. Each project gets its own daemon.

A project can describe itself in `shotkit.config.json` at its root. Every field
is optional:

```json
{
  "app": {
    "dir": "web",
    "mockScript": "dev:mock",
    "mockEnv": { "UI_MOCK": "1" },
    "mockHeader": "x-mock",
    "mockProbe": "/api/health"
  },
  "backdrop": { "canvas": "scripts/canvas.js", "size": "1920x1080", "pixelated": false }
}
```

| | |
|---|---|
| `app.dir` | where the frontend lives, relative to the root (default `.`) |
| `app.mockScript` | the package.json script `--mock` runs (default `dev:mock`) |
| `app.mockEnv` | extra environment for that script |
| `app.mockHeader` / `app.mockProbe` | a response header (value `1`) on a route that proves a running dev server is the mock one; without it, any running dev server is attached to |
| `backdrop.canvas` | a canvas script for `--backdrop canvas` (see **The desktop**) |
| `backdrop.size` | the page the script paints on, `WxH` in CSS px (default `1920x1080`) |
| `backdrop.pixelated` | upscale the painting hard-edged, for pixel art (default `false`, smooth) |

## Why it is fast

A screenshot script that launches a browser per invocation spends about two
seconds doing the same three things every time. shotkit pays them once:

| | |
|---|---|
| **A daemon holds the browser.** | First shot ~2s, every later shot ~150ms. It starts itself, and shuts down after 15 idle minutes. |
| **Cards never touch the network.** | `term`, `code` and `html` render a self-contained document into a page that stays open. No navigation, no fetches. |
| **`--mock` boots the app once.** | The dev server is held by the daemon, not by the request, so six shots of six routes boot it once. A mock server already running is reused; with `app.mockHeader` set, a dev server in front of real data is refused rather than shot as if it were the mocks (Next allows one per folder, so stop it first). |
| **`--offline` skips dead CDNs.** | An app that links Google Fonts or another CDN. Where those are unreachable, waiting on them costs ~13s *per navigation* — more than everything else combined. `shot doctor` probes for this, and a slow capture says so. |

```
$ shot bench
cold (no daemon, includes browser launch): 2142ms
warm x6: min 134ms · median 163ms · max 486ms
speedup: 13.1x
```

## The commands

| | |
|---|---|
| `shot app [route]` | the running frontend; `--mock` boots the project's `dev:mock` script |
| `shot url <url>` | any URL |
| `shot term <command…>` | run a command, shoot its terminal output |
| `shot text <file\|->` | render an existing ANSI capture |
| `shot code <file>` | a syntax-highlighted code card |
| `shot html <file\|->` | render an HTML document |
| `shot video [route]` | record a short take — see **Video** |
| `shot open` / `do` / `shoot` / `close` | drive a page held open — see **Navigation** |
| `shot warm` / `status` / `stop` / `serve` | the daemon |
| `shot doctor` / `bench` | check and time this machine |

`--backdrop` takes `canvas` or `glass` (the project's own background — see **The desktop**),
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
shot term --cols 84 --title git -- git status
shot term --command "pytest -q" -- uv run pytest -q              # run one thing, show another
shot text ci-failure.log --window plain                           # a capture you already have
```

Colors come from a muted dark/light palette rather than the stock VGA one, so a
terminal card sits next to an app screenshot without clashing.

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
shot app /settings --do click:Profile --do wait:.avatar --do scroll:bottom
```

For anything longer, hold the page open. The daemon keeps it under a name, so
you can look, decide, and act, without replaying the flow from a cold load each
time — and each shot is ~250ms.

```bash
shot open /settings --session r --viewport laptop
shot do click:Profile --session r
shot shoot --session r --name negotiate
shot shoot click:Plan sleep:300 --session r --name plan   # act and shoot in one call
shot sessions ; shot close --session r
```

Element arguments accept any Playwright selector engine (`text=`,
`role=button[name="Save"]`, `#id`, `//xpath`). A bare word is matched by
accessible name, then by visible text — `click:Save` means the button labeled
Save, not a `<save>` element. Words that are also tag names are no exception:
`click:table` prefers a control labeled "table", and only falls back to the
`<table>` element when nothing carries that label. Phrases are labels too —
`click:Save changes` is a button, not a descendant selector — so a selector made
only of tag names and spaces needs saying explicitly: `css=nav button`.

## Signed in

A page behind a login (SSO, Keycloak, anything with a cookie session) is shot
signed in by loading a saved login. The browser shotkit drives is headless and
keeps nothing between runs, so the login happens once, by a person, in a
visible browser:

```bash
npx playwright open --save-storage=$HOME/.shotkit/staging.json https://staging.example.com
# sign in as usual, then close the window
shot url https://staging.example.com/dashboard --storage-state ~/.shotkit/staging.json
```

`--storage-state` works on `app`, `url`, `open` and `video`, and
`SHOTKIT_STORAGE_STATE` sets a default. The file is Playwright's storage state
(cookies and localStorage per origin), loaded when the context is created.
shotkit never reads, prints or copies it. Re-saving it (the session expired, the
shots show the login page again) takes effect on the next shot, since contexts
are pooled per file *and* its modification time.

The file is a session credential: keep it in your home directory, never in a
repo, and never in `.shotkit/`, which is only gitignored, not private.

## Video

`shot video` records the same flow a screenshot would take, as a short clip with
a pointer in it:

```bash
shot video /settings --do click:Profile --do wait:.avatar --auto-zoom
shot video / --mock --do 'fill:#search=aligner' --do press:Enter --format mp4
shot video https://example.com --do 'zoom:.pricing@2' --do zoomout --fps 24
```

The action vocabulary is the one `--do` already speaks — a recording is not a
second script format. What changes is how each verb is performed:

| | |
|---|---|
| **The pointer travels.** | It eases to each target and the real mouse goes with it, so hover states, tooltips and drag affordances light up on the way. |
| **The click reads.** | A ring expands where the press lands, and the cursor dips — at 30fps a click is otherwise a frame with nothing in it. |
| **The camera pushes in.** | `zoom:<sel>` frames an element; `--auto-zoom` does it for every click and pulls back after. It is a transform on the page, so the type is re-rasterized sharper, not scaled up. |
| **Typing is typed.** | `fill:` clicks the field and enters the text a character at a time. |

A few extra verbs, ignored outside a recording, so one action list can serve
both a take and the stills pulled from the same flow:

```
zoom:<sel>  zoom:<sel>@2.2  zoom:2  zoomout   hold:<ms>
caption:<text>   caption:   speed:<n>
```

**Captions.** `caption:<text>` puts a line of text over the take and cross-fades
to the next one; an empty `caption:` clears it. It sits at the bottom, or at the
top with `--caption-at top` when the bottom is where the flow types.

**Fast-forward.** `speed:<n>` plays what follows at n times (up to 16) by keeping
one frame in n, and `speed:1` returns to real time. It is for waits on something
live, like a model answering: `speed:5` before a `wait:` and `speed:1` after it
turns a two-minute wait into a watchable half-minute. `--max-seconds` counts the
clip, not the wall clock, so a fast-forwarded stretch can run longer than it.

The camera crops into the frame as it stands, so it never asks the page for
content it has not painted; a push-in near an edge slides back inside instead of
panning off. While it is pushed in, a `position: fixed` element travels with the
page rather than sticking, and an element the crop has cut off is brought back by
pulling the camera out before acting on it.

**Format.** `--format mp4|webm|gif`, defaulting to the best the machine's ffmpeg
can write. Playwright ships one with its browsers — always present, but built
webm-only — so mp4 and gif need a full ffmpeg on PATH (or `SHOTKIT_FFMPEG`).
`shot doctor` says which you have.

**Timing.** `--fps` (30), `--move-ms` (620), `--dwell` (620), `--zoom-ms` (620),
`--press-ms` (110), `--lead-in` (500), `--tail` (1000), and `--max-seconds` (90)
to stop a runaway take. Frames come from a CDP screencast — real time, the app's
own transitions included; `--capture shots` falls back to a screenshot loop.
Whichever it is, a frame is written every 1/fps whether the page changed or not,
so the file's timeline is wall-clock and a still stretch costs repeats of one
JPEG.

## Sound

A take can come out with the sound of the person driving it: a soft low tock
on each click, a quiet tick per keystroke (spread unevenly over the span a
string was typed in, as a hand types) and a heavier one for a key pressed on
its own, like Enter. Over a bed, if you give it one.

```bash
shot video /settings --do click:Profile --do "fill:Name=Sam" --do press:Enter --sound
shot video /settings --demo --do click:Profile --sound --bed ~/music/ambient.mp3
shot sound .shotkit/video-settings.mp4 --bed ambient.mp3 --bed-db -9   # re-mix a take
```

**Cues.** Every take writes `<video>.sounds.json` beside it: each click and key
at the second it shows in the finished video, and each typed string with the
span it went in over. Placing them is the part that matters. A press is noted
at the animation frame that paints it, and lands on the first video frame drawn
after that, by the screencast's own frame timestamps. Noting "the frame being
written right now" instead puts sounds early whenever the app is busy: its
compositor keeps sending frames of the old picture for a while after a click.
Measured against the picture, a click's sound lands within one frame (33ms) of
the press. Speed-ups and title cards are already folded in.

**The mix.** A bed (any file ffmpeg reads, looped or cut to the take's length)
is brought to −23 LUFS, the clicks sit at a fixed size over it, and `--target`
(−19) sets how loud the pair is together. `--bed-db` (−6) then moves the bed
alone, so turning it down leaves the clicks where they were. With no bed the
clicks are leveled by their peak instead (−6 dBFS at the default target), since
a few clicks in silence meter near −40 LUFS and loudness is the wrong ruler.
`--click-db` and `--key-db` trim each kind; `--no-foley` keeps the bed alone.
A look-ahead limiter holds the master under −1.9 dBFS. The build prints the
finished loudness (BS.1770-4) and the 4x-oversampled true peak, since those are
the numbers that say whether it is too loud.

**Needs a full ffmpeg.** Sound is AAC in an mp4 and Opus in a webm, and
Playwright's bundled ffmpeg has neither; a gif has no sound at all. `--sound`
checks before the take starts, so a minute of recording isn't lost to the wrong
ffmpeg. The picture is copied into the muxed file, not re-encoded.

**As a library.** `import { addSound, mixSoundtrack } from "shotkit/audio"`. A
project that scores its own bed renders a stereo pair with the primitives there
(oscillators, a state-variable filter, pink noise, an FDN reverb, envelopes,
wavetables, the compressor, limiter and loudness meter) and passes it as `bed`;
the clicks, the leveling and the mux stay shotkit's:

```js
import { addSound, makeBus, hz, rng } from "shotkit/audio";
const bed = myScore(durationSeconds, 48000); // { L: Float64Array, R: Float64Array }
await addSound("demo.mp4", { bed, bedDb: -6, target: -19 });
```

## Browser chrome

`--chrome` re-renders a page capture inside the same window frame the terminal
cards use, with an address bar:

```bash
shot app /settings --chrome --backdrop dusk
shot app / --chrome --theme light                 # app and frame both light
shot app / --chrome --theme dark --chrome-theme light
```

`--theme` drives the app's own theme, not just the browser's `prefers-color-scheme`:
next-themes reads `localStorage` before first paint and would otherwise ignore it.

## Tech-demo framing

`--demo` puts the shot on a stage: tilted in perspective, floating over a dark
ground with a soft accent glow behind it, the angled product shot from a launch
page. It works on `app`, `url`, `shoot`, `term`, `text`, `code`, `html` and
`video`.

```bash
shot app / --demo                                  # the hero angle
shot app / --demo --chrome                         # with the browser window bar
shot code src/server.ts --range 40:80 --tilt right --reflect
shot url https://example.com --tilt dutch          # a flat dutch tilt, no 3D
shot term --tilt 10,-24,3 -- git log --oneline -8  # your own angles, in degrees
shot video /settings --demo --do click:Profile --drift 14
```

`--tilt` takes a preset (`hero`, `left`, `right`, `dutch`, `desk`, `flat`) or
`x,y,z` in degrees: x tips the top away, y turns the window to face left or
right, z is the dutch angle. One number is a dutch tilt on its own. Any
`--tilt` implies `--demo`.

| | |
|---|---|
| `--perspective <px>` | camera distance; smaller is more dramatic (default 1800) |
| `--fit <0-1>` | how much of the stage the flat window fills (default 0.74) |
| `--stage <WxH>` | stage size in CSS px (default 1920x1080; a still is at `--scale`, so 3840x2160 by default) |
| `--no-glow` / `--reflect` / `--grid` | drop the glow; add a faint reflection; add a perspective grid on the ground |
| `--backdrop` | the ground, as everywhere else; unset, the stage uses its own near-black (or near-white with `--theme light`) |
| `--drift <deg>` | video only: swing the angle this far across the take, with a slow push in (default 10, `0` holds still) |

On a staged take the words belong to the stage, not the page. A `caption:`
is drawn flat over the tilted window, a headline and, after a `|`, the line
under it (`caption:Hand it a task|Every task is a row and a thread.`), and
`--intro` / `--outro` open and close the take on a title card in the same form,
with the project's logo above it. The faces, the accent and the logo come from
`stage` in `shotkit.config.json`:

```json
"stage": {
  "fonts": "https://fonts.googleapis.com/css2?family=…",
  "titleFont": "\"Cormorant Garamond\", Georgia, serif",
  "titleStyle": "italic 600",
  "textFont": "\"IBM Plex Sans\", system-ui, sans-serif",
  "accent": "#5dd4e0",
  "logo": "docs/logo.png"
}
```

| | |
|---|---|
| `--intro <title\|line>` / `--outro` | a title card before or after the take, cross-faded into the window |
| `--title-seconds <s>` | how long each card holds (default 2.6) |
| `--caption-at top` | captions top-left rather than bottom-left; the window shifts to make room |

A still is re-rendered once, the way `--chrome` is: the browser does the 3D,
so the type stays sharp instead of being resampled. A video is recorded as
usual to a spool on disk, then each frame is put on the stage and encoded
after the take ends, which is what lets the camera drift across the whole of
it. That pass costs about 25ms a frame spread over four pages; with
`--drift 0`, a stretch where nothing moves is rendered once.

## The desktop

`--backdrop canvas` puts the project's own background behind the window (the
animated scene a docs site paints behind its pages, say), so a framed
screenshot sits on the product's desktop rather than a gradient:

```bash
shot app /settings --chrome --backdrop canvas --padding 90
shot term --backdrop canvas -- git log --oneline -8
shot app / --demo --backdrop canvas
```

shotkit carries no painting of its own: the project names a script in
`shotkit.config.json` (`backdrop.canvas`). The script is an IIFE that draws
into `<canvas id="mycelium-bg">`. It can read the `dark` or `light` class on
`<html>` and the `--canvas-bg`, `--canvas-ink` and `--canvas-alpha` custom
properties, and it should paint one still frame under
`prefers-reduced-motion`, which every shotkit page sets. 2D canvas and WebGL
both work. It paints on a `backdrop.size` page (1920x1080 by default; many
scenes scale to the page, so this is also their density), and the result is
upscaled smoothly, or hard-edged with `backdrop.pixelated` for pixel art.
Without a configured script this backdrop errors and the others are
unaffected.

In mycelium, the older pixel hypha network is
`scripts/banner-assets/mycelial-canvas.js` (with `"pixelated": true` and
`"size": "1600x900"`, the density it was tuned at). The docs' glass droplets
can run here too, as a still, but `--backdrop glass` below does more with them.

A vignette in the ground's own color veils it, lightly in the middle and
heavily at the edges. A site can run its background at full strength because
prose sits on near-solid paper above it; a screenshot has no such pane, and an
unveiled background pulls the eye into the corners and away from the window.
Light is veiled less than dark, since light already runs at a lower alpha.

One painting is made per theme and held for the life of the daemon, so a run
of shots shares one desktop and only the first pays to paint it. It is painted
from a fixed seed (shotkit replaces `Math.random`), so the same command gives
the same background tomorrow and a committed asset does not churn on every
re-render; `--backdrop-seed <n>` asks for a different one.

`--backdrop glass` is for a scene that can be stepped by hand, so it moves
during a video rather than holding still. In mycelium that is the docs' glass
droplets (`docs/glass.js`, the file the docs load): drops of iridescent glass
drifting up, reaching for each other with hyphae, now and then pooling into
one. The project names the script in `backdrop.glass`; it runs in WebGL with
`Math.random` seeded, and must honor `window.__glassManual` (skip its own
animation loop), `window.__glassScale` (draw at a fraction of the page's
resolution) and `window.__glass.seek(frame)` (step to a frame of a 30fps clock
and draw). A still gets one frame. A staged video gets the scene live under the
window, stepped one frame of the take at a time, so every page the take is
staged on holds the same scene at the same beat; it is drawn at half
resolution and re-drawn at 15fps, since a software GL spends most of a frame on
it and the drops drift slowly.

The other backdrops (`mycelium`, `dusk`, `ink`, `paper`, `none`, or any CSS you
pass) are unchanged, and are what to reach for when a shot wants quiet behind
it: a painted background is texture, and texture competes with a busy screen.

## The library

```js
import { capture, shutdown } from "shotkit";   // or a path to src/api.mjs

const r = await capture({ op: "app", route: "/", responsive: true, sheet: true });
r.path;      // absolute path of the sheet
r.shots;     // one entry per breakpoint
await shutdown();
```

In-process captures use the same engine as the CLI, without the daemon: useful
for a script that publishes a set of committed screenshots.

## Waiting

An app capture waits for a *populated* frame, not a mounted one, using three
hooks an app can opt into:

- `data-app-shell="ready"` on the layout once it has mounted. With no
  `data-app-shell` attribute on the page at all, this step is skipped after a
  second.
- `.animate-pulse` skeletons (Tailwind's loading placeholder) all gone.
- a `data-connection` element reading `live`, for an app with a live stream. A
  shot taken a moment early otherwise catches a "Reconnecting…" badge, which
  reads as a broken app.

An app with none of them is shot once it has loaded and its fonts are ready.

`--settle full` raises every budget for a slow backend; `--settle none` skips the
lot when you want the frame exactly as it loads.

## Notes

- **macOS and Linux.** Both need `script(1)` (present by default) for terminal
  cards, and a Chromium. `shot doctor` says what is missing.
- **Any Chromium will do.** Playwright pins an exact build and refuses others;
  shotkit falls back to `executablePath` for whatever is on disk, so a version
  skew between the driver and the host's browser is not a re-download.
- **Editing shotkit restarts the daemon.** It stamps its own source at boot and
  the client replaces it when that moves, so a fix never silently runs stale.
- **Behind an egress proxy**, Chromium reads no `HTTPS_PROXY`; set
  `SHOTKIT_PROXY` to the proxy's URL and the browser uses it (loopback still
  goes direct). The proxy's CA has to be trusted by Chromium's NSS store.
- **Captures land in `.shotkit/`** (gitignored) and overwrite by name; `--unique`
  timestamps instead.
- **A take costs about what it lasts.** Encoding keeps up with capture, so a
  ten-second video takes about ten seconds plus the flow's own waits.
