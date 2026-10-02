<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- Copyright 2026 Mycelium Contributors -->

# mycelium-promo — the product demo

`mycelium-demo.mp4` is one take of the real app, recorded with shotkit: the
frontend running in its demo scenario, driven click by click, and staged on a
tilted window over the docs site's glass droplets.

The story is one coffee shop's checkout room:

1. **You name yourself**, and add @builder, a coding agent on your machine.
2. **You hand it a task**: customers are charged twice when they double-click
   Pay. @builder claims it in the task's thread.
3. **One builds, another reviews.** In the thread, `@conductor review @builder
   @reviewer` runs the review flow: a fix, a finding sent back, a test, approval.
   The flow's graph shows every edge taken.
4. **They disagree, and the aligner helps.** @reviewer files the decision the
   fix raised (refund automatically, or send to support?), the two take sides,
   and `@aligner` brokers an agreement.
5. **It lands on the board**: the agreement compiles into two new tasks.

## Files

| | |
|---|---|
| `demo.json` | the take: shotkit's options and its `do` action list, in the vocabulary of `shot video --do` |
| `record.mjs` | boots the frontend in the demo scenario and records `demo.json` through shotkit's library |
| `mycelium-demo.mp4` | the recording, 1920x1080 H.264. Not committed (git-ignored); see Publishing |

The agents' side of the story is the frontend's demo scenario
(`MYCELIUM_UI_MOCK_SCENARIO=demo`, `mycelium-frontend/src/mocks/demo.ts`):
fixture data and a director that answers what you do, with no hub and no model.
Everything on screen is the app's own UI.

## Recording

```bash
cd mycelium-frontend && npm ci      # once; shotkit borrows its Playwright
node mycelium-promo/record.mjs --quick   # the flow alone, flat, ~2 min: check it first
node mycelium-promo/record.mjs           # the staged take → mycelium-promo/mycelium-demo.mp4
node mycelium-promo/audio/build.mjs mycelium-promo/mycelium-demo.mp4   # its sound → mycelium-demo-sound.mp4
```

The sound is a gentle drone with the take's clicks and keystrokes on it, timed
from the `mycelium-demo.mp4.sounds.json` the take writes beside the video. See
[`audio/README.md`](audio/README.md).

`record.mjs` starts its own `next dev` (the scenario's acts play once per
server), so stop any dev server in `mycelium-frontend/` first. The staged take
needs a full ffmpeg on `PATH` for mp4 (`node shotkit/bin/shot.mjs doctor`
says), and the fonts load from Google Fonts. Behind an egress proxy, set
`SHOTKIT_PROXY`. Staging is a pass after the take; on a laptop with a GPU it is
quick, and in a software-GL container it is a few minutes per minute of video.

To change the story, edit the copy in `demo.ts` and the beats in `demo.json`.
A `wait-text:` is what holds the take until an agent has spoken, and `speed:`
fast-forwards the waits.

## Publishing

The README and `docs/index.html` embed the video from a
`user-attachments/assets/...` URL. Those only play inline when uploaded through
GitHub's web drag-and-drop, so after re-recording, drag the new mp4 into a PR
comment to mint a URL, then swap it into both embeds.
