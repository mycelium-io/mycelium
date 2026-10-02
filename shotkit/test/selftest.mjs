// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * A smoke test for the parts that hold real logic and no browser: the ANSI
 * screen buffer, the highlight-line splitter, the argument parser and the
 * network policy. These are where the subtle bugs live — a `\r` that stacks two
 * frames into one image, a resolver rule that silently disables itself — and
 * they are all pure functions, so they can be checked without a Chromium.
 *
 *   node test/selftest.mjs
 */

import assert from "node:assert/strict";
import { ansiToHtml, parseAnsi, stripAnsi } from "../src/ansi.mjs";
import { splitHighlightedLines, guessLanguage } from "../src/code.mjs";
import { parse } from "../src/args.mjs";
import { policyArgs, policyKey } from "../src/network.mjs";
import { resolveViewport, viewportList } from "../src/viewports.mjs";
import { locate, parseAction } from "../src/actions.mjs";
import { backdrop, palette } from "../src/theme.mjs";
import { ART_RENDERING, CANVAS_VARS, VEIL, canvasDocument } from "../src/canvas.mjs";
import { CANVAS_PIXELATED } from "../src/project.mjs";
import { cardDocument } from "../src/card.mjs";
import { encodeArgs, findEncoder, forgetEncoder, jpegSize, startEncoder } from "../src/encode.mjs";
import { parseZoom } from "../src/video.mjs";
import { startPump } from "../src/pump.mjs";
import { TILT_PRESETS, driftAt, isStaged, parseStageSize, parseTilt, stageDocument } from "../src/stage.mjs";
import { startSpool } from "../src/restage.mjs";
import { rng } from "../src/audio/dsp.mjs";
import { limit, lufs, samplePeakDb, truePeakDb } from "../src/audio/master.mjs";
import { readCues, writeCues } from "../src/audio/cues.mjs";
import { renderFoley } from "../src/audio/foley.mjs";
import { encodeWav, soundFfmpeg } from "../src/audio/io.mjs";
import { mixSoundtrack, soundOptions } from "../src/audio/soundtrack.mjs";
import { existsSync, mkdtempSync, utimesSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Engine, frameOf, requireStorageState, storageStateKey } from "../src/engine.mjs";

let failures = 0;
function test(name, fn) {
  try {
    fn();
    process.stdout.write(`  \x1b[32m✓\x1b[0m ${name}\n`);
  } catch (err) {
    failures += 1;
    process.stdout.write(`  \x1b[31m✗\x1b[0m ${name}\n    ${err.message}\n`);
  }
}

async function atest(name, fn) {
  try {
    await fn();
    process.stdout.write(`  \x1b[32m✓\x1b[0m ${name}\n`);
  } catch (err) {
    failures += 1;
    process.stdout.write(`  \x1b[31m✗\x1b[0m ${name}\n    ${err.message}\n`);
  }
}

const text = (input) => parseAnsi(input).map((r) => r.runs.map((x) => x.text).join(""));

const stateDir = mkdtempSync(join(tmpdir(), "shotkit-state-"));
const stateFile = join(stateDir, "login.json");
writeFileSync(stateFile, JSON.stringify({ cookies: [], origins: [] }));

test("a saved login rides on the frame into the context options", () => {
  const frame = frameOf({ storageState: stateFile });
  assert.equal(frame.storageState, stateFile);
  assert.equal(new Engine().contextOptions(frame).storageState, stateFile);
  assert.equal("storageState" in new Engine().contextOptions(frameOf({})), false);
});

test("a missing saved login says how to make one", () => {
  const missing = join(stateDir, "nope.json");
  assert.throws(() => requireStorageState(missing), /npx playwright open --save-storage=/);
  assert.throws(() => frameOf({ storageState: missing }), /no saved login/);
});

test("re-saving a login changes the pool key, so stale cookies are not reused", () => {
  const before = storageStateKey(stateFile);
  const later = new Date(Date.now() + 5_000);
  utimesSync(stateFile, later, later);
  assert.notEqual(storageStateKey(stateFile), before);
  assert.equal(storageStateKey(undefined), "anon");
});

test("carriage return overwrites the line rather than appending", () => {
  assert.deepEqual(text("first\rsecond"), ["second"]);
});

test("erase-to-end clears the tail a shorter repaint leaves behind", () => {
  assert.deepEqual(text("aaaaaaa\rbb\x1b[K"), ["bb"]);
});

test("cursor-up repaints the row instead of adding one", () => {
  assert.deepEqual(text("one\ntwo\n\x1b[2A\x1b[Kuno"), ["uno", "two"]);
});

test("a trailing newline does not add a blank row", () => {
  assert.equal(parseAnsi("only\n").length, 1);
});

test("tabs advance to the next 8-column stop", () => {
  assert.deepEqual(text("ab\tc"), ["ab      c"]);
});

test("SGR colors resolve against the theme, bold picks the bright slot", () => {
  const pal = palette("dark");
  const { html } = ansiToHtml("\x1b[31mred\x1b[0m \x1b[1;31mbright\x1b[0m", pal);
  assert.ok(html.includes(pal.ansi[1]), "expected the red slot");
  assert.ok(html.includes(pal.ansi[9]), "expected the bright red slot");
});

test("256-color and truecolor become rgb", () => {
  const { html } = ansiToHtml("\x1b[38;5;208morange\x1b[0m\x1b[38;2;1;2;3mexact\x1b[0m", palette("dark"));
  assert.ok(html.includes("rgb(255,135,0)"));
  assert.ok(html.includes("rgb(1,2,3)"));
});

test("html is escaped, so output cannot inject markup", () => {
  const { html } = ansiToHtml("<script>alert(1)</script>", palette("dark"));
  assert.ok(!html.includes("<script>"));
  assert.ok(html.includes("&lt;script&gt;"));
});

test("OSC 8 hyperlinks are dropped but keep their text", () => {
  assert.deepEqual(text("\x1b]8;;https://example.com\x07label\x1b]8;;\x07"), ["label"]);
});

test("stripAnsi leaves plain text", () => {
  assert.equal(stripAnsi("\x1b[1;36mhi\x1b[0m"), "hi");
});

test("splitting highlighted lines reopens spans across the break", () => {
  const lines = splitHighlightedLines('<span class="hljs-comment">a\nb</span>c');
  assert.equal(lines.length, 2);
  assert.equal(lines[0], '<span class="hljs-comment">a</span>');
  assert.ok(lines[1].startsWith('<span class="hljs-comment">b</span>'));
});

test("language is guessed from the extension", () => {
  assert.equal(guessLanguage("src/api.mjs"), "javascript");
  assert.equal(guessLanguage("app/services/l9.py"), "python");
  assert.equal(guessLanguage("config.toml"), "ini");
});

test("term stops parsing its own flags at the command", () => {
  const { flags, rest } = parse(
    ["--cols", "84", "mycelium", "memory", "ls", "--room", "atlas"],
    { cols: { type: "number" }, room: { type: "string" } },
    { stopAtPositional: true },
  );
  assert.equal(flags.cols, 84);
  assert.equal(flags.room, undefined, "--room belongs to the child command");
  assert.deepEqual(rest, ["mycelium", "memory", "ls", "--room", "atlas"]);
});

test("--no-<flag> negates a boolean", () => {
  const { flags } = parse(["--no-shadow"], { shadow: { type: "boolean" } });
  assert.equal(flags.shadow, false);
});

test("repeatable and key=value flags accumulate", () => {
  const { flags } = parse(
    ["--do", "click:A", "--do", "wait:.b", "--env", "K=V"],
    { do: { type: "list" }, env: { type: "map" } },
  );
  assert.deepEqual(flags.do, ["click:A", "wait:.b"]);
  assert.deepEqual(flags.env, { K: "V" });
});

test("an unknown option is an error, not a silent drop", () => {
  assert.throws(() => parse(["--nope"], {}), /unknown option/);
});

test("an open policy adds no launch args", () => {
  assert.deepEqual(policyArgs({}), []);
  assert.equal(policyKey({}), "open");
});

test("offline excludes localhost by name and never by IP literal", () => {
  const [arg] = policyArgs({ offline: true });
  assert.ok(arg.includes("MAP * ~NOTFOUND"));
  assert.ok(arg.includes("EXCLUDE localhost"));
  // An IP literal here makes Chromium reject the whole rule string silently.
  assert.ok(!arg.includes("127.0.0.1"), "an IP literal would disable every rule");
});

test("blocked hosts become resolver failures", () => {
  assert.deepEqual(policyArgs({ block: ["fonts.googleapis.com"] }), [
    "--host-resolver-rules=MAP fonts.googleapis.com ~NOTFOUND",
  ]);
});

test("viewports accept presets and explicit sizes", () => {
  assert.equal(resolveViewport("phone").width, 390);
  assert.deepEqual(
    { ...resolveViewport("1280x800@1.5"), label: undefined },
    { width: 1280, height: 800, scale: 1.5, label: undefined },
  );
  assert.throws(() => resolveViewport("enormous"), /unknown viewport/);
});

test("--responsive expands to the breakpoint ladder", () => {
  assert.deepEqual(viewportList({ responsive: true }).map((v) => v.name), [
    "phone",
    "tablet",
    "laptop",
    "wide",
  ]);
  assert.deepEqual(viewportList({}), []);
});

test("an action splits on its first colon only", () => {
  assert.deepEqual(parseAction("fill:#q=a:b"), { verb: "fill", arg: "#q=a:b" });
  assert.deepEqual(parseAction("reload"), { verb: "reload", arg: "" });
});

test("a zoom argument splits into a target and a factor", () => {
  assert.deepEqual(parseZoom("out", 1.6), { target: "", z: 1 });
  assert.deepEqual(parseZoom("2", 1.6), { target: "", z: 2 });
  assert.deepEqual(parseZoom("#panel", 1.6), { target: "#panel", z: 1.6 });
  assert.deepEqual(parseZoom("#panel@2.2", 1.6), { target: "#panel", z: 2.2 });
  // A selector may hold digits and colons; only the tail after @ is a factor.
  assert.deepEqual(parseZoom("text=Save 2", 1.6), { target: "text=Save 2", z: 1.6 });
});

test("the encoder is fed frames on a pipe and writes even dimensions", () => {
  const args = encodeArgs({ format: "mp4", fps: 30, width: 1281, height: 801, out: "/tmp/a.mp4" });
  // A bare "-" is not a protocol Playwright's stripped ffmpeg registers.
  assert.ok(args.includes("pipe:0"));
  assert.ok(args.includes("scale=1280:800"), "4:2:0 refuses odd dimensions");
  assert.ok(args.includes("libx264"));
  assert.equal(encodeArgs({ format: "webm", fps: 30, width: 640, height: 400, out: "/tmp/a.webm" })
    .includes("libvpx"), true);
  assert.throws(() => encodeArgs({ format: "mov", fps: 30, width: 2, height: 2, out: "x" }), /unknown video format/);
});

test("a jpeg's size comes out of its frame header", () => {
  // SOI, an APP0 whose length must be skipped, then SOF0 carrying 200x100.
  const jpeg = Buffer.from([
    0xff, 0xd8,
    0xff, 0xe0, 0x00, 0x04, 0x00, 0x00,
    0xff, 0xc0, 0x00, 0x11, 0x08, 0x00, 0x64, 0x00, 0xc8, 0x03, 0, 0, 0, 0, 0, 0, 0, 0, 0,
  ]);
  assert.deepEqual(jpegSize(jpeg), { width: 200, height: 100 });
  assert.deepEqual(jpegSize(Buffer.from([0xff, 0xd8])), { width: 0, height: 0 });
});

test("a backdrop preset resolves per theme, and unknown values pass through", () => {
  assert.equal(backdrop("canvas", "dark"), CANVAS_VARS.dark.bg);
  assert.equal(backdrop("canvas", "light"), CANVAS_VARS.light.bg);
  assert.equal(backdrop("#123456", "dark"), "#123456");
});

test("the canvas harness carries the theme's canvas vars", () => {
  const html = canvasDocument("/* script */", { theme: "light" });
  assert.ok(html.includes(`--canvas-ink:${CANVAS_VARS.light.ink}`));
  assert.ok(html.includes(`--canvas-alpha:${CANVAS_VARS.light.alpha}`));
  assert.ok(html.includes('<html class="light">'), "a script reads the theme off <html>");
  assert.ok(html.includes('id="mycelium-bg"'), "the script looks the canvas up by id");
});

test("one seed paints one scene", () => {
  const a = canvasDocument("/* script */", { seed: 7 });
  assert.ok(a.includes("var s=7;"), "the seed replaces Math.random before the script runs");
  assert.notEqual(a, canvasDocument("/* script */", { seed: 8 }));
  assert.equal(a, canvasDocument("/* script */", { seed: 7 }));
});

test("--tilt reads a preset, three angles, or one dutch angle", () => {
  assert.deepEqual(parseTilt(undefined), TILT_PRESETS.hero);
  assert.deepEqual(parseTilt("left"), TILT_PRESETS.left);
  assert.deepEqual(parseTilt("-8,18,-6"), [-8, 18, -6]);
  assert.deepEqual(parseTilt("12"), [0, 0, 12]);
  assert.throws(() => parseTilt("sideways"), /preset/);
  assert.throws(() => parseTilt("1,2,3,4"), /preset/);
});

test("the stage is asked for by --demo or any --tilt, and sized by --stage", () => {
  assert.equal(isStaged({}), false);
  assert.equal(isStaged({ demo: true }), true);
  assert.equal(isStaged({ tilt: "dutch" }), true);
  assert.deepEqual(parseStageSize("1280x720"), { width: 1280, height: 720 });
  assert.throws(() => parseStageSize("wide"), /WxH/);
});

test("drift swings the angle across a take and holds it at zero", () => {
  const tilt = [10, -20, 4];
  const a = driftAt(tilt, 10, 0);
  const b = driftAt(tilt, 10, 1);
  assert.equal(b.tilt[1] - a.tilt[1], 10, "y sweeps the whole drift");
  assert.equal(driftAt(tilt, 10, 0.5).tilt[1], -20, "the midpoint is the configured angle");
  assert.equal(a.tilt[2], 4, "the dutch angle holds");
  assert.deepEqual(driftAt(tilt, 0, 0.3), { tilt, zoom: 1 });
});

test("the stage document carries its options", () => {
  const html = stageDocument({ imgWidth: 1280, imgHeight: 800, tilt: [0, 0, -7], reflect: true, glow: false });
  assert.ok(html.includes("rotateZ(-7deg)"));
  assert.ok(html.includes("-webkit-box-reflect"));
  assert.ok(!html.includes('id="glow"'));
});

test("the spool keeps one file per distinct frame and the order of beats", async () => {
  const spool = startSpool();
  try {
    const a = Buffer.from("a");
    const b = Buffer.from("b");
    for (const f of [a, a, a, b, b, a]) spool.write(f);
    assert.deepEqual(spool.order, [0, 0, 0, 1, 1, 2]);
    assert.equal(spool.read(1).toString(), "b");
    assert.deepEqual(await spool.finish(), { frames: 6 });
  } finally {
    spool.remove();
  }
  assert.equal(existsSync(spool.dir), false);
});

test("the vignette veils light less than dark", () => {
  // The site already runs light at a lower canvas alpha; veiling both equally
  // washes the network out of the cream entirely.
  assert.ok(CANVAS_VARS.light.alpha < CANVAS_VARS.dark.alpha);
  for (const [i, stop] of VEIL.light.entries()) assert.ok(stop < VEIL.dark[i], `stop ${i}`);
});

test("a card grows an artwork layer only when there is artwork", () => {
  assert.ok(!cardDocument("hi", { backdrop: "ink" }).includes('id="art"'));
  const art = cardDocument("hi", { backdrop: "canvas", art: "url(data:image/png;base64,AA) center/cover" });
  assert.ok(art.includes('id="art"'));
  // Whichever the project running the test asks for: smooth by default, hard
  // edges where its shotkit.config.json says pixelated.
  assert.ok(art.includes(`image-rendering:${ART_RENDERING}`), "the art layer upscales the way the project said");
  assert.equal(ART_RENDERING, CANVAS_PIXELATED ? "pixelated" : "auto");
});

/**
 * A stand-in for a Playwright page. Each locator records how it was built and
 * reports a count from `present`, whose entries are `"<kind>:<arg>"` — `label`
 * for the accessible-name/text chain, `css` for a plain selector. Counts are all
 * `locate` consults.
 */
function fakePage(present) {
  const mk = (kind, arg) => ({
    kind,
    arg,
    first: () => mk(kind, arg),
    or: (other) => ({ ...mk("label", arg), alternatives: [kind, other.kind], first: () => mk("label", arg) }),
    count: async () => (present.includes(`${kind}:${arg}`) ? 1 : 0),
  });
  return {
    locator: (sel) => mk("css", sel),
    getByRole: (role, o) => mk("role", o.name),
    getByText: (t) => mk("text", t),
    getByPlaceholder: (t) => mk("placeholder", t),
  };
}

await (async () => {
  const acount = atest;

  await acount("a selector with punctuation stays CSS", async () => {
    const r = await locate(fakePage([]), ".offer-grid");
    assert.equal(r.kind, "css");
  });

  await acount("a selector-engine prefix is passed through", async () => {
    const r = await locate(fakePage([]), 'role=button[name="Save"]');
    assert.equal(r.kind, "css");
  });

  await acount("a bare word that is not a tag name resolves by label", async () => {
    const r = await locate(fakePage([]), "Negotiate");
    assert.equal(r.kind, "label");
  });

  await acount("a label wins over the same word as a tag name", async () => {
    // A button labeled "table" and a <table> both on the page: the label is
    // what the caller typed and what they meant.
    const r = await locate(fakePage(["label:table", "css:table"]), "table");
    assert.equal(r.kind, "label");
  });

  await acount("a multi-word label is a label, not a descendant selector", async () => {
    // `page.locator("Save changes")` is valid CSS — a <changes> inside a <Save>
    // — so getting this wrong fails silently rather than throwing.
    const r = await locate(fakePage([]), "Save changes");
    assert.equal(r.kind, "label");
  });

  await acount("a phrase of tag names is still a label", async () => {
    const r = await locate(fakePage(["css:nav button"]), "nav button");
    assert.equal(r.kind, "label");
  });

  await acount("an explicit css= prefix still reaches the selector engine", async () => {
    const r = await locate(fakePage([]), "css=nav button");
    assert.equal(r.kind, "css");
  });

  await acount("the tag is used only when no label matches it", async () => {
    const r = await locate(fakePage(["css:select"]), "select");
    assert.equal(r.kind, "css");
  });

  await acount("neither present falls back to the label, for a legible error", async () => {
    const r = await locate(fakePage([]), "form");
    assert.equal(r.kind, "label");
  });
})();

/* ── The recording lifecycle ────────────────────────────────────────────────
 * The pump and the encoder are where a take can hang rather than fail, so they
 * are exercised here with a source that is an object and an "ffmpeg" that is
 * `/bin/false` — no browser, no codec, and every death path reachable.
 * ────────────────────────────────────────────────────────────────────────── */

/** A 1x1 JPEG header: enough for jpegSize, which is all the pump reads. */
const FRAME = Buffer.from([
  0xff, 0xd8,
  0xff, 0xc0, 0x00, 0x11, 0x08, 0x00, 0x01, 0x00, 0x01, 0x03, 0, 0, 0, 0, 0, 0, 0, 0, 0,
  0xff, 0xd9,
]);

const heldSource = (frame = FRAME) => ({ mode: "test", latest: frame, stop: async () => {} });

/** An encoder that counts, without spawning anything. */
function fakeEncoder(overrides = {}) {
  const enc = {
    frames: 0,
    saturated: false,
    failure: null,
    finished: 0,
    killed: 0,
    write() {
      enc.frames += 1;
      return true;
    },
    async finish() {
      enc.finished += 1;
      return { frames: enc.frames };
    },
    kill() {
      enc.killed += 1;
    },
    ...overrides,
  };
  return enc;
}

const wait = (ms) => new Promise((r) => setTimeout(r, ms));
/** A program that runs and exits non-zero: `/bin/false` on Linux, `/usr/bin/false` on macOS. */
const FALSE_BIN = existsSync("/bin/false") ? "/bin/false" : "/usr/bin/false";

await (async () => {
  await atest("a dead ffmpeg is reported, not waited on forever", async () => {
    // The exit listener is registered immediately on spawn: a process that
    // dies on its arguments emits `close` once before `finish()` would be
    // called, so a listener set inside `finish()` would miss it.
    const enc = startEncoder({ format: "webm", fps: 30, width: 64, height: 64, out: "/tmp/shotkit-dead.webm", ffmpeg: FALSE_BIN });
    await wait(200);
    for (let i = 0; i < 3; i++) enc.write(FRAME);
    const outcome = await Promise.race([
      enc.finish().then(() => "resolved", (e) => e.message),
      wait(3_000).then(() => "HUNG"),
    ]);
    assert.match(outcome, /ffmpeg exited/, `expected ffmpeg's exit, got: ${outcome}`);
  });

  await atest("an ffmpeg that cannot be spawned at all is reported too", async () => {
    const enc = startEncoder({ format: "webm", fps: 30, width: 64, height: 64, out: "/tmp/x.webm", ffmpeg: "/nonexistent/ffmpeg" });
    enc.write(FRAME);
    const outcome = await Promise.race([
      enc.finish().then(() => "resolved", (e) => e.code ?? e.message),
      wait(3_000).then(() => "HUNG"),
    ]);
    assert.equal(outcome, "ENOENT");
  });

  await atest("finishing twice gives the same answer, not a second wait", async () => {
    const enc = startEncoder({ format: "webm", fps: 30, width: 64, height: 64, out: "/tmp/x.webm", ffmpeg: "/bin/false" });
    enc.write(FRAME);
    const first = await enc.finish().catch((e) => e.message);
    const second = await Promise.race([enc.finish().catch((e) => e.message), wait(2_000).then(() => "HUNG")]);
    assert.equal(second, first);
  });

  await atest("the pump writes the held frame on every beat", async () => {
    const enc = fakeEncoder();
    const pump = startPump({ source: heldSource(), fps: 50, maxFrames: 1000, encoder: () => enc });
    await wait(220);
    const { frames, width, height } = await pump.stop();
    // A still page still costs a frame per beat: the file's timeline is
    // wall-clock, not change-driven.
    assert.ok(frames >= 4, `expected several beats, got ${frames}`);
    assert.deepEqual({ width, height }, { width: 1, height: 1 });
    assert.equal(enc.finished, 1);
  });

  await atest("the frame cap stops the writing and says so", async () => {
    const enc = fakeEncoder();
    const pump = startPump({ source: heldSource(), fps: 50, maxFrames: 3, encoder: () => enc });
    await wait(250);
    const { frames } = await pump.stop();
    assert.equal(frames, 3);
    assert.equal(pump.truncated, true);
  });

  await atest("a sped-up stretch writes one frame per n beats", async () => {
    const real = fakeEncoder();
    const pump = startPump({ source: heldSource(), fps: 50, maxFrames: 1000, encoder: () => real });
    await wait(300);
    const { frames: atOne } = await pump.stop();

    const fast = fakeEncoder();
    const lapse = startPump({ source: heldSource(), fps: 50, maxFrames: 1000, encoder: () => fast });
    lapse.setSpeed(4);
    await wait(300);
    const { frames: atFour } = await lapse.stop();
    // The same stretch, a quarter of the frames: it plays four times faster.
    assert.ok(atFour <= Math.ceil(atOne / 4) + 1, `4x wrote ${atFour} of ${atOne}`);
    assert.ok(atFour >= 2, `4x still writes frames, got ${atFour}`);
  });

  await atest("the cap counts the video, and reaching it ends the take", async () => {
    const enc = fakeEncoder();
    const pump = startPump({ source: heldSource(), fps: 50, maxFrames: 3, encoder: () => enc });
    pump.setSpeed(2);
    const why = await Promise.race([pump.trouble, wait(2000).then(() => "timeout")]);
    assert.equal(why, "over");
    await pump.stop();
    assert.equal(pump.truncated, true);
  });

  test("speed is clamped between real time and the top speed", () => {
    const pump = startPump({ source: heldSource(), fps: 50, maxFrames: 10, encoder: () => fakeEncoder() });
    pump.setSpeed(0.2);
    assert.equal(pump.speed, 1);
    pump.setSpeed(1000);
    assert.equal(pump.speed, 16);
    void pump.abort();
  });

  await atest("a beat that fails raises at the end rather than on the timer", async () => {
    // Thrown from a setTimeout callback this would be an uncaught exception in
    // whatever process is hosting the daemon.
    const pump = startPump({
      source: heldSource(Buffer.from([1, 2, 3])),
      fps: 50,
      maxFrames: 100,
      encoder: () => fakeEncoder(),
    });
    await wait(120);
    await assert.rejects(() => pump.stop(), /readable JPEG/);
  });

  await atest("an encoder that dies mid-take ends the take early", async () => {
    const enc = fakeEncoder({ failure: new Error("ffmpeg exited 1") });
    const pump = startPump({ source: heldSource(), fps: 50, maxFrames: 100, encoder: () => enc });
    const why = await Promise.race([pump.trouble, wait(2_000).then(() => "NEVER")]);
    assert.equal(why, "encoder");
    await assert.rejects(() => pump.stop(), /ffmpeg exited 1/);
  });

  await atest("a page that never produced a frame is a clear failure", async () => {
    const pump = startPump({
      source: { mode: "test", latest: null, stop: async () => {} },
      fps: 50,
      maxFrames: 100,
      encoder: () => fakeEncoder(),
    });
    await wait(80);
    await assert.rejects(() => pump.stop(), /never produced a frame/);
  });

  await atest("an ffmpeg named by hand is never quietly replaced", async () => {
    const before = process.env.SHOTKIT_FFMPEG;
    process.env.SHOTKIT_FFMPEG = "/bin/false";
    forgetEncoder();
    try {
      await assert.rejects(() => findEncoder(), /SHOTKIT_FFMPEG/);
    } finally {
      if (before === undefined) delete process.env.SHOTKIT_FFMPEG;
      else process.env.SHOTKIT_FFMPEG = before;
      forgetEncoder();
    }
  });

  await atest("aborting still closes the file, and leaves no timer behind", async () => {
    const enc = fakeEncoder();
    const pump = startPump({ source: heldSource(), fps: 50, maxFrames: 100, encoder: () => enc });
    await wait(120);
    await pump.abort();
    assert.equal(enc.finished, 1);
    assert.equal(enc.killed, 0);
  });

  await atest("a moment is placed on the first frame that shows it, not the one being written", async () => {
    // Frames drawn 300ms before they reach the pump, as a slow screencast does.
    const source = { mode: "screencast", latest: FRAME, latestAt: 0, stop: async () => {} };
    const lag = setInterval(() => (source.latestAt = Date.now() - 300), 5);
    const pump = startPump({ source, fps: 50, maxFrames: 1000, encoder: () => fakeEncoder() });
    try {
      await wait(400);
      const moment = Date.now();
      const writtenThen = pump.frames;
      await wait(600);
      // The frame showing `moment` reaches the pump 300ms later, so it lands
      // ~15 frames (at 50fps) after the one that was being written at the time.
      const placed = pump.frameAt(moment);
      assert.ok(placed - writtenThen >= 10, `placed at ${placed}, written then ${writtenThen}`);
      assert.equal(pump.frameAt(0), 0);
      assert.equal(pump.frameAt(Date.now() + 60_000), pump.frames - 1, "after the last frame, the last frame");
    } finally {
      clearInterval(lag);
      await pump.stop();
    }
  });

  await atest("the pump's frame count is the take's clock for its cues", async () => {
    const enc = fakeEncoder();
    const pump = startPump({ source: heldSource(), fps: 50, maxFrames: 1000, encoder: () => enc });
    await wait(100);
    assert.equal(pump.frames, enc.frames);
    assert.ok(pump.frames > 0);
    await pump.stop();
  });
})();

// ── sound ────────────────────────────────────────────────────────────────
const SR = 48000;
const sine = (hzf, seconds, amp = 1, sr = SR, phase = 0) =>
  Float64Array.from({ length: Math.round(seconds * sr) }, (_, i) => amp * Math.sin(2 * Math.PI * hzf * (i / sr) + phase));

test("a full-scale 1kHz tone in one channel meters -3.01 LUFS (BS.1770's reference)", () => {
  const L = sine(1000, 5);
  assert.ok(Math.abs(lufs(L, new Float64Array(L.length), SR) + 3.01) < 0.1);
});

test("loudness is right at 44.1kHz too, not only the published 48kHz", () => {
  const L = sine(1000, 5, 1, 44100);
  assert.ok(Math.abs(lufs(L, new Float64Array(L.length), 44100) + 3.01) < 0.1);
});

test("silence has no loudness, rather than a NaN", () => {
  const z = new Float64Array(SR);
  assert.equal(lufs(z, z, SR), -Infinity);
});

test("the true peak finds what sits between samples", () => {
  // A quarter-rate sine sampled 45 degrees off its crest never shows its peak.
  const L = sine(SR / 4, 0.1, 1, SR, Math.PI / 4);
  const R = new Float64Array(L.length);
  assert.ok(samplePeakDb(L, R) < -2.9, "the samples stop at -3 dB");
  assert.ok(truePeakDb(L, R) > -0.5, "the waveform reaches 0 dB between them");
});

test("the limiter holds every sample under its ceiling", () => {
  const L = sine(220, 0.5, 2);
  const R = sine(330, 0.5, 2);
  limit(L, R, SR, { ceiling: 0.8 });
  for (let i = 0; i < L.length; i++) assert.ok(Math.abs(L[i]) <= 0.8 + 1e-9 && Math.abs(R[i]) <= 0.8 + 1e-9);
});

test("a WAV is a RIFF header and four bytes a frame", () => {
  const buf = encodeWav(new Float64Array(10), new Float64Array(10), SR);
  assert.equal(buf.toString("ascii", 0, 4), "RIFF");
  assert.equal(buf.length, 44 + 40);
  assert.equal(buf.readUInt32LE(24), SR);
});

test("cues round-trip, placed after an intro card", () => {
  const dir = mkdtempSync(join(tmpdir(), "shotkit-cues-"));
  const video = join(dir, "take.mp4");
  writeCues(video, [{ beat: 30, kind: "click" }, { beat: 60, end: 90, kind: "type", chars: 4 }], 30, 15);
  assert.deepEqual(readCues(video), [
    { t: 1.5, kind: "click" },
    { t: 2.5, t1: 3.5, kind: "type", chars: 4 },
  ]);
  assert.deepEqual(readCues(join(dir, "none.mp4")), [], "no cue file is no cues");
});

test("foley is the same file twice, and lands where its cues say", () => {
  const cues = [{ t: 0.5, kind: "click" }, { t: 1, t1: 1.4, kind: "type", chars: 6 }, { t: 1.8, kind: "key" }];
  const a = renderFoley(2.2, cues, SR);
  const b = renderFoley(2.2, cues, SR);
  assert.deepEqual(a.L, b.L, "seeded, so reproducible");
  const energy = (from, to) => {
    let e = 0;
    for (let i = Math.round(from * SR); i < Math.round(to * SR); i++) e += a.L[i] * a.L[i];
    return e;
  };
  assert.ok(energy(0, 0.49) === 0, "nothing before the first click");
  assert.ok(energy(0.5, 0.6) > 0 && energy(1.0, 1.45) > 0 && energy(1.8, 1.9) > 0);
});

test("a soundtrack with no cues and no bed is silent, not broken", () => {
  const t = mixSoundtrack(1, []);
  assert.equal(t.left.length, SR);
  assert.ok(t.left.every((x) => x === 0));
  assert.equal(t.lufs, -Infinity);
});

test("a bed comes up under the clicks, and the master stays under its ceiling", () => {
  const n = SR * 3;
  const r = rng(5);
  const noise = () => Float64Array.from({ length: n }, () => (r() * 2 - 1) * 0.3);
  const t = mixSoundtrack(3, [{ t: 1, kind: "click" }], { bed: { L: noise(), R: noise() } });
  assert.ok(Number.isFinite(t.lufs) && t.lufs > -30 && t.lufs < -10, `got ${t.lufs}`);
  assert.ok(t.samplePeakDb <= 20 * Math.log10(0.8) + 1e-6);
});

test("--bed-db moves the bed and leaves the clicks where they were", () => {
  const n = SR * 3;
  const r = rng(9);
  // Noise with a hole around the click, so what sounds there is the click alone.
  const hole = (i) => i > 1.3 * SR && i < 1.8 * SR;
  const bed = {
    L: Float64Array.from({ length: n }, (_, i) => (hole(i) ? 0 : (r() * 2 - 1) * 0.2)),
    R: new Float64Array(n),
  };
  const cues = [{ t: 1.5, kind: "click" }];
  const loud = mixSoundtrack(3, cues, { bed, bedDb: -3, ceiling: 10 });
  const quiet = mixSoundtrack(3, cues, { bed, bedDb: -12, ceiling: 10 });
  const i = Math.round(1.505 * SR);
  assert.ok(Math.abs(loud.left[i]) > 1e-4, "the click is there");
  assert.equal(loud.left[i], quiet.left[i], "and the same size under either bed level");
  assert.ok(loud.lufs > quiet.lufs, "while the bed itself moved");
});

test("the mix options come out of a spec, and nothing else does", () => {
  assert.deepEqual(soundOptions({ op: "video", bed: "/m.mp3", bedDb: -9, sound: true, fps: 30 }), { bed: "/m.mp3", bedDb: -9 });
});

await atest("a gif is refused sound up front, before a take is spent on it", async () => {
  await assert.rejects(() => soundFfmpeg("gif"), /no sound track/);
});


process.stdout.write(failures ? `\n${failures} failing\n` : "\nall passing\n");
process.exit(failures ? 1 : 0);
