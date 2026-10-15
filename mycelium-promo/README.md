<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- Copyright 2026 Mycelium Contributors -->

# mycelium-promo — the product demo

`mycelium-demo.mp4` is one take of the real app, recorded with shotkit: the
frontend running in its demo scenario, driven click by click, and staged on a
tilted window over the docs site's glass droplets.

The story is one coffee shop's checkout room:

1. **You name yourself**, and add @builder, a coding agent on your machine.
2. **You make a task from a message**: customers are charged twice when they
   double-click Pay. Its thread opens, and you hand it to @builder by
   mentioning it there.
3. **Agents ask each other.** @builder claims it and asks @reviewer, who
   answers in the thread. A card shows the wake message @reviewer was woken
   with (`wake-card.js`: the web app has no view of an agent's terminal, so
   this is the one thing on screen that isn't the app's own UI).
4. **One builds, another reviews.** In the thread, `@conductor review
   @~builder @~reviewer` runs the review flow (`@~` names the members without
   waking them; the conductor asks each in turn): a fix, a finding sent back,
   a test, approval. Meanwhile the room's other threads move, and the Stream
   shows them side by side in lanes. The flow's graph shows every edge taken.
5. **They disagree, and the aligner helps.** @reviewer files the decision the
   fix raised (refund automatically, or send to support?), the two take sides,
   and `@aligner` brokers an agreement.
6. **It lands on the board**: the agreement compiles into two new tasks.

## Files

| | |
|---|---|
| `demo.json` | the take: shotkit's options and its `do` action list, in the vocabulary of `shot video --do` |
| `record.mjs` | boots the frontend in the demo scenario and records `demo.json` through shotkit's library; an `eval:file:<name>` action runs a script from this folder in the page |
| `wake-card.js` | the wake message card shown over the app (`eval:file:wake-card.js`), in the wake message's own layout |
| `mycelium-demo.mp4` | the recording, 1920x1080 H.264. Not committed (git-ignored); see Publishing |

The agents' side of the story is the frontend's demo scenario
(`MYCELIUM_UI_MOCK_SCENARIO=demo`, `mycelium-frontend/src/mocks/demo.ts`):
fixture data and a director that answers what you do, with no hub and no model.
Everything on screen is the app's own UI, except the wake card.

## Recording

```bash
cd mycelium-frontend && npm ci      # once; shotkit borrows its Playwright
scripts/sync-shotkit.sh                  # optional: bring shotkit/ up to the latest shotkit first
node mycelium-promo/record.mjs --quick   # the flow alone, flat and silent, ~2 min: check it first
node mycelium-promo/record.mjs           # the staged take, with its sound → mycelium-promo/mycelium-demo.mp4
```

That last command is everything: it records the take, stages it, and gives it
its sound, a gentle drone with the take's clicks and keystrokes on it, placed
from the `mycelium-demo.mp4.sounds.json` the take writes beside the video.
`--no-sound` leaves it silent, and `audio/build.mjs` re-mixes a take without
re-recording it. See [`audio/README.md`](audio/README.md).

`record.mjs` starts its own `next dev` (the scenario's acts play once per
server), so stop any dev server in `mycelium-frontend/` first. The staged take
needs a full ffmpeg on `PATH` for mp4 (`node shotkit/bin/shot.mjs doctor`
says), and the fonts load from Google Fonts. Behind an egress proxy, set
`SHOTKIT_PROXY`. Staging is a pass after the take; on a laptop with a GPU it is
quick, and in a software-GL container it is a few minutes per minute of video.

To change the story, edit the copy in `demo.ts` and the beats in `demo.json`.
A `wait-text:` is what holds the take until an agent has spoken, and `speed:`
fast-forwards the waits. Zoom out before anything opens or closes a pane (a
thread, a task, a tab): the room's panes lay a new one out at the camera's
zoomed size, and it stays drawn too wide after the camera pulls back.

## Publishing

The docs site plays `docs/demo/mycelium-demo.mp4`, committed through Git LFS
(every `*.mp4` under `docs/` is), so after re-recording, copy the take there,
re-encoded smaller: the take comes out around 1.8 Mb/s, three times what the
page needs, and every visitor and every Pages deploy downloads all of it.

```bash
ffmpeg -i mycelium-promo/mycelium-demo.mp4 -c:v libx264 -crf 30 -preset slow \
  -pix_fmt yuv420p -c:a copy -movflags +faststart docs/demo/mycelium-demo.mp4
```
The README can't play a file from the repo: GitHub only plays a README video
inline from a `user-attachments/assets/...` URL, minted by dragging the mp4
into a PR comment in the browser. Swap that URL into the README by hand.

## The Learn videos

Each section of a course on `learn.html` opens with a short video of the app
doing what its lessons teach, recorded the same way as the demo: shotkit
driving the real UI over a mock scenario, here the frontend's Learn scenario
(`MYCELIUM_UI_MOCK_SCENARIO=learn:<take>`, `mycelium-frontend/src/mocks/learn.ts`).
Its `orders` room starts in the state the take needs, and a director plays the
agents' side.

```bash
node mycelium-promo/learn/record.mjs                    # every take → docs/learn/video/
node mycelium-promo/learn/record.mjs pair-idea github   # just these
node mycelium-promo/learn/record.mjs --raw swarm-run    # keep the take as recorded, in .shotkit/learn/, to check it
```

| | |
|---|---|
| `learn/takes/<take>.json` | one take: shotkit options and its `do` actions, as `demo.json` |
| `learn/record.mjs` | boots a server per take, records it, encodes it for the web (H.264, no sound) with a poster, and writes its length into `docs/learn/video/index.json` |
| `server.mjs` | the dev server a take runs against, shared with `record.mjs` |

A section names its take as `video` in its `course.json`; `generate_docs.py`
fails if that take isn't recorded. The videos are committed through Git LFS,
like the demo, and the docs site serves them. To change what an agent says, edit
`learn.ts`; to change what the camera does, edit the take. A take that waits on
the agents with `wait-text:` stays in step with the director whatever its
pacing (`PACE` in `learn.ts`).
