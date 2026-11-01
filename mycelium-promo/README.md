<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- Copyright 2026 Mycelium Contributors -->

# mycelium-promo — the product demo

`mycelium-demo.mp4` is one take of the real app, recorded with shotkit: the
frontend running in its demo scenario, driven click by click, and staged on a
tilted window over the docs site's glass droplets.

The story is one coffee shop's checkout room:

1. **You name yourself**, and add @builder, a coding agent on your machine.
2. **Agents are members.** You welcome @builder by name in the channel, and it
   answers.
3. **The board.** You add a task for @builder on the board (customers are
   charged twice when they double-click Pay), and it takes it.
4. **Agents coordinate the same way.** In the task's thread, @builder asks
   @reviewer to check the fix, @reviewer asks for a test, and @builder adds
   one, all by mentioning each other.
5. **One place for the work.** @builder uploads a recording of the fix
   (`clip/checkout.html`, five taps and one charge), it plays in the room,
   @reviewer approves, you say ship it, and the Files pane shows it.
6. **A week later** (`fade.js`, the one thing on screen that isn't the app's
   own UI): the room has grown to a team of agents, each on a task of its own,
   every thread moving. The channel, then the Stream with every thread in its
   own lane, then the board.

## Files

| | |
|---|---|
| `demo.json` | the take: shotkit's options and its `do` action list, in the vocabulary of `shot video --do` |
| `record.mjs` | records the clip @builder uploads, boots the frontend in the demo scenario, and records `demo.json` through shotkit's library; an `eval:file:<name>` action runs a script from this folder in the page |
| `clip/checkout.html` | the coffee shop's checkout on a phone, for the clip (`.shotkit/demo/double-tap-one-charge.mp4`, handed to the scenario as `MYCELIUM_DEMO_CLIP`) |
| `fade.js` | the time skip (`eval:file:fade.js`): fades to "A week later", grows the room (`POST /api/demo/busy`), and `window.__fade.out()` fades back |
| `mycelium-demo.mp4` | the recording, 1920x1080 H.264. Not committed (git-ignored); see Publishing |

The agents' side of the story is the frontend's demo scenario
(`MYCELIUM_UI_MOCK_SCENARIO=demo`, `mycelium-frontend/src/mocks/demo.ts`):
fixture data and a director that answers what you do, with no hub and no model.
Everything on screen is the app's own UI, except the fade.

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
server), so stop any dev server in `mycelium-frontend/` first. Every run,
`--quick` too, records the checkout clip as an mp4 first, so it needs a full
ffmpeg on `PATH` (`node shotkit/bin/shot.mjs doctor` says); Playwright's own
ffmpeg writes only webm. The fonts load from Google Fonts. Behind an egress proxy, set
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
