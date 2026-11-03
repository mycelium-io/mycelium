#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Record the workshop's multiplayer videos: a replay of a real run in the
 * `release-planning` room, driven through `takes/<take>.json` over the
 * frontend's workshop scenario (`MYCELIUM_UI_MOCK_SCENARIO=workshop:<take>`,
 * `src/mocks/workshop.ts`).
 *
 *   node mycelium-promo/workshop/record.mjs                       # every take → ../slides/workshop/media/
 *   node mycelium-promo/workshop/record.mjs accord --out ~/tmp     # one take, somewhere else
 *   node mycelium-promo/workshop/record.mjs --raw concord          # keep the take as recorded
 *
 * Each take is the app seen as Julia, at 1920x1080, silent and without
 * captions (the talk is spoken over it). It's encoded for the web and gets a
 * poster frame at `poster` seconds.
 */

import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, readdirSync, renameSync, rmSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { capture, shutdown } from "../../shotkit/src/api.mjs";
import { refuseIfRunning, startScenario } from "../server.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "../..");
const SCRATCH = join(repo, ".shotkit/workshop");

/** What every take shares: Julia's browser, the room, the camera. Each
 *  person's laptop is listed as one of hers, so the Members rail names the
 *  machine each agent runs on (it names only your own). */
const DEFAULTS = {
  route: "/room/release-planning",
  // 1920x1080 out, from a 1280x720 window at 1.5x: the app fills the frame
  // at a size a room can read, rather than a wide window of small type.
  // (Given as width, height and scale: a take ignores a viewport's ratio.
  // The screencast sends CSS pixels, so the frames are screenshots.)
  width: 1280,
  height: 720,
  scale: 1.5,
  capture: "shots",
  theme: "dark",
  format: "mp4",
  fps: 30,
  maxSeconds: 240,
  actionTimeout: 90000,
  moveMs: 650,
  dwell: 450,
  leadIn: 700,
  tail: 1600,
  // The page is the team's app in a browser: the offers to install the app
  // and the CLI are for someone new.
  hide: ["a:has(> .lucide-download)", 'button[aria-label="Install CLI"]'],
  // A flow take's captions say what each step does. They're a popover beside
  // the thread, over the board (no take needs it then), pointing at the flow,
  // in the docs' type: the step's name in the title face, the line in the text face.
  css: `
    @import url("https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@1,600&family=IBM+Plex+Sans:wght@400;500&display=swap");
    #__shotkit-overlay #__shotkit-caption {
      left: 2.2%; right: auto; top: 15%; bottom: auto;
      width: 33%; max-width: none; transform: translateX(-8px);
      padding: 16px 20px 18px; border-radius: 10px; text-align: left;
      background: rgba(14, 17, 21, 0.96); border: 1px solid rgba(93, 212, 224, 0.45);
      font: italic 600 30px/1.1 "Cormorant Garamond", Georgia, serif; color: #5dd4e0;
    }
    #__shotkit-overlay #__shotkit-caption.__shotkit-on { transform: translateX(0); }
    #__shotkit-overlay #__shotkit-caption::after {
      content: ""; position: absolute; right: -7px; top: 26px; width: 12px; height: 12px;
      background: inherit; border: inherit; border-left: 0; border-bottom: 0; transform: rotate(45deg);
    }
    #__shotkit-overlay #__shotkit-caption .__shotkit-sub {
      margin-top: 8px; opacity: 1; color: #e6e9ec;
      font: 400 17px/1.45 "IBM Plex Sans", -apple-system, system-ui, sans-serif;
    }
  `,
  storage: {
    "mycelium.principal": "julia",
    "mycelium.name-asked": "1",
    "mycelium.machines": JSON.stringify(["julias-mbp", "jodees-mbp", "marcs-mbp"]),
  },
};

/** The team talking in its other rooms as the take opens, so three of them
 *  wear an unread badge. Said live: a badge is what arrives while you're here. */
const OTHER_ROOMS = [
  ["roadmap", "jodee", "Moved widgets to Q1."],
  ["roadmap", "marc", "Agreed, after offline mode."],
  ["support-escalations", "lena", "Two more tickets about lost changes."],
  ["support-escalations", "lena", "One is the pilot customer."],
  ["support-escalations", "sam", "Looking now."],
  ["mobile-app", "priya", "4.12 branch builds on both platforms."],
];
/** A spotlight instead of a camera move: everything but one area is softly
 *  blurred and dimmed, and the area follows its element as the page scrolls.
 *  A take calls `window.__spot(css, text?, exact?, withNext?)`, or passes an
 *  element; `window.__spot()` lifts it. `withNext` takes in the element after
 *  the match too (a heading and what's under it). */
const SPOTLIGHT = `eval:(() => {
  if (window.__spot) return;
  const veil = document.createElement('div');
  Object.assign(veil.style, {
    position: 'fixed', inset: '0', zIndex: '2147483000', pointerEvents: 'none', opacity: '0',
    backdropFilter: 'blur(2.5px) brightness(0.55)', transition: 'opacity 450ms ease',
  });
  document.body.appendChild(veil);
  let target = null;
  const rect = () => {
    const r = target[0].getBoundingClientRect();
    const s = target[1]?.getBoundingClientRect() ?? r;
    return { left: Math.min(r.left, s.left), top: Math.min(r.top, s.top), right: Math.max(r.right, s.right), bottom: Math.max(r.bottom, s.bottom) };
  };
  const tick = () => {
    if (target && target[0].isConnected) {
      const r = rect(), p = 8;
      const [x1, y1, x2, y2] = [r.left - p, r.top - p, r.right + p, r.bottom + p].map((v) => v + 'px');
      veil.style.clipPath = 'polygon(evenodd, 0 0, 100% 0, 100% 100%, 0 100%, 0 0, ' + [x1 + ' ' + y1, x2 + ' ' + y1, x2 + ' ' + y2, x1 + ' ' + y2, x1 + ' ' + y1].join(', ') + ')';
    }
    requestAnimationFrame(tick);
  };
  tick();
  window.__spot = (what, text, exact, withNext) => {
    const el = what instanceof Element ? what : !what ? null
      : [...document.querySelectorAll(what)].filter((e) => !text || (exact ? e.textContent.trim() === text : e.textContent.includes(text))).at(-1);
    target = el ? [el, withNext ? el.nextElementSibling : null] : null;
    veil.style.opacity = target ? '1' : '0';
  };
})()`;
const OTHER_ROOMS_TALK =`eval:(async () => { for (const [room, sender_handle, content] of ${JSON.stringify(OTHER_ROOMS)}) await fetch('/api/rooms/' + room + '/messages', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ sender_handle, content }) }); })()`;

const argv = process.argv.slice(2);
const raw = argv.includes("--raw");
const outAt = argv.indexOf("--out");
const OUT = resolve(outAt >= 0 ? argv[outAt + 1] : join(repo, "../../slides/workshop/media"));
const all = readdirSync(join(here, "takes"))
  .filter((f) => f.endsWith(".json"))
  .map((f) => f.slice(0, -5));
const named = argv.filter((a, i) => !a.startsWith("--") && argv[i - 1] !== "--out");
const takes = named.length ? named : all;
for (const t of takes) {
  if (!all.includes(t)) {
    console.error(`no take ${t}; there are: ${all.join(", ")}`);
    process.exit(2);
  }
}

refuseIfRunning();
mkdirSync(OUT, { recursive: true });
mkdirSync(SCRATCH, { recursive: true });

const ffmpeg = (...args) => execFileSync("ffmpeg", ["-loglevel", "error", "-y", ...args], { stdio: "inherit" });
const mb = (path) => (statSync(path).size / 1e6).toFixed(1);

for (const take of takes) {
  const spec = JSON.parse(readFileSync(join(here, "takes", `${take}.json`), "utf8"));
  const { $comment, poster = 3, ...flow } = spec;
  const [first, ...rest] = flow.do;
  const shot = {
    ...DEFAULTS,
    ...flow,
    storage: { ...DEFAULTS.storage, ...(flow.storage ?? {}) },
    // Once the room is up, the rest of the team talks elsewhere.
    do: [first, OTHER_ROOMS_TALK, SPOTLIGHT, ...rest],
  };
  const { baseUrl, stop } = await startScenario(`workshop:${take}`, [shot.route]);
  try {
    const recorded = join(SCRATCH, `${take}.mp4`);
    const result = await capture(
      { op: "video", ...shot, baseUrl, out: recorded },
      { log: (m) => console.error(`[${take}] ${m}`) },
    );
    const seconds = Math.round(result.durationMs / 100) / 10;
    console.error(`[${take}] ${result.frames} frames, ${seconds}s, ${result.width}x${result.height}`);
    if (raw) {
      console.log(result.path);
      continue;
    }
    const video = join(OUT, `${take}.mp4`);
    const tmp = join(SCRATCH, `${take}.web.mp4`);
    ffmpeg(
      "-i", result.path,
      "-an", "-c:v", "libx264", "-preset", "slow", "-crf", "24",
      "-pix_fmt", "yuv420p", "-movflags", "+faststart",
      tmp,
    );
    renameSync(tmp, video);
    ffmpeg("-ss", String(poster), "-i", result.path, "-frames:v", "1", "-q:v", "3", join(OUT, `${take}.jpg`));
    rmSync(`${result.path}.sounds.json`, { force: true });
    console.log(`${video} (${mb(video)} MB, ${seconds}s)`);
  } finally {
    await stop();
  }
}
await shutdown();
