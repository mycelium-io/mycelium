<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- Copyright 2026 Mycelium Contributors -->

# mycelium-deck: the slide template

A slide deck in plain HTML, for talks and workshops. It uses the docs' palette
and type (Cormorant Garamond italic for display, IBM Plex Sans, Geist Mono).
The background is new: instead of a field of glass droplets, one glass lens
moves across a mycelial network. The network keeps growing for as long as the
deck is open, and pulses run along its hyphae. The lens magnifies whatever is
under it, and it moves from slide to slide like a drop of gel, stretching
along its path.

## Presenting

Open `index.html` in Chrome. There is no build step and no server. It needs
`../docs/` beside it for the logo and screenshots, and the internet for the
fonts. Without a connection the type falls back to Georgia and system fonts.

| Key | |
|---|---|
| → Space PageDown | next step, then next slide (clickers send these) |
| ← PageUp | back |
| O | overview of every slide; click a tile to jump to it |
| S | speaker view: notes, what comes next, elapsed time, the clock |
| F | fullscreen |
| T | light / dark (light suits a bright room or a weak projector) |
| B or . | blackout |
| a number, then ⏎ | go to that slide |
| ? | the key list |

The URL hash is the slide number (`index.html#7`). To make a PDF, print from
Chrome with background graphics on. Each slide prints as one 1920×1080 page
with a still lens drawn in CSS.

## Writing slides

Each slide is a `<section class="slide">` on a 1920×1080 stage. Lay slides
out in stage pixels and the deck scales them to fit the screen.

```html
<section class="slide" data-title="Agenda" data-lens="1600 600 250">
  <span class="kicker rise">The next 90 minutes</span>
  <h2 class="rise">Agenda</h2>
  …
  <aside class="notes"><p>Shown in the speaker view.</p></aside>
</section>
```

- `data-lens="x y r"` is where the lens sits and how big it is, in stage
  pixels. Give up to three, separated by commas (`"1520 470 330, 1130 860 54"`
  is a lens with a bead beside it), or `none`.
- `data-title` names the slide in the tab and the speaker view.
- `data-bare` hides the footer.
- `.rise` elements arrive one after another when their slide opens.
- `.step` elements are revealed one per key press before the deck moves on. A
  step with its own `data-lens` moves the lens while it is the latest one shown.
- `.pane` is frosted glass. Use it for anything that sits over the lens.
- `<div class="timer" data-minutes="10" style="--x:1500px; --y:560px">` is a
  countdown centred on that point: click to start or pause, double-click to
  reset. The exercise slide centres one on its lens.

The sample deck has one slide for each layout: `layout-title`, a terminal
(`layout-terminal`), an agenda (`.agenda`), `layout-section`,
`layout-statement`, `.cards`, `layout-diagram` (an SVG in stage coordinates
with the lens over its centre), a flow of `.step`s, `.numbers`,
`layout-exercise` with a timer, `layout-image`, `.compare` and `layout-close`.
Copy the one closest to what you need.

## Files

| | |
|---|---|
| `index.html` | the slides |
| `deck.css` | palette (dark, and light under `data-theme="light"`), type, layouts, print |
| `deck.js` | fitting the stage, keys, steps, overview, speaker view, timers |
| `lens.js` | the background: grows the network on a 2D canvas, then draws it with the lens in one WebGL shader |

With `prefers-reduced-motion`, the network is drawn once and the lens jumps
between positions. Without WebGL, the CSS lens from print is used on screen.
