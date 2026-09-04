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
import { CANVAS_VARS, VEIL, networkDocument } from "../src/mycelial.mjs";
import { cardDocument } from "../src/card.mjs";
import { encodeArgs, findEncoder, forgetEncoder, jpegSize, startEncoder } from "../src/encode.mjs";
import { parseZoom } from "../src/video.mjs";
import { startPump } from "../src/pump.mjs";

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
  assert.equal(backdrop("mycelial", "dark"), CANVAS_VARS.dark.bg);
  assert.equal(backdrop("mycelial", "light"), CANVAS_VARS.light.bg);
  assert.equal(backdrop("#123456", "dark"), "#123456");
});

test("the network harness carries the theme's canvas vars", () => {
  const html = networkDocument("/* algorithm */", { theme: "light" });
  assert.ok(html.includes(`--canvas-ink:${CANVAS_VARS.light.ink}`));
  assert.ok(html.includes(`--canvas-alpha:${CANVAS_VARS.light.alpha}`));
  assert.ok(html.includes('id="mycelium-bg"'), "the algorithm looks the canvas up by id");
});

test("one seed grows one network", () => {
  const a = networkDocument("/* algorithm */", { seed: 7 });
  assert.ok(a.includes("var s=7;"), "the seed replaces Math.random before the algorithm runs");
  assert.notEqual(a, networkDocument("/* algorithm */", { seed: 8 }));
  assert.equal(a, networkDocument("/* algorithm */", { seed: 7 }));
});

test("the vignette veils light less than dark", () => {
  // The site already runs light at a lower canvas alpha; veiling both equally
  // washes the network out of the cream entirely.
  assert.ok(CANVAS_VARS.light.alpha < CANVAS_VARS.dark.alpha);
  for (const [i, stop] of VEIL.light.entries()) assert.ok(stop < VEIL.dark[i], `stop ${i}`);
});

test("a card grows an artwork layer only when there is artwork", () => {
  assert.ok(!cardDocument("hi", { backdrop: "ink" }).includes('id="art"'));
  const art = cardDocument("hi", { backdrop: "mycelial", art: "url(data:image/png;base64,AA) center/cover" });
  assert.ok(art.includes('id="art"'));
  assert.ok(art.includes("image-rendering:pixelated"), "the cells must not blur when upscaled");
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

await (async () => {
  await atest("a dead ffmpeg is reported, not waited on forever", async () => {
    // The exit listener is registered immediately on spawn: a process that
    // dies on its arguments emits `close` once before `finish()` would be
    // called, so a listener set inside `finish()` would miss it.
    const enc = startEncoder({ format: "webm", fps: 30, width: 64, height: 64, out: "/tmp/shotkit-dead.webm", ffmpeg: "/bin/false" });
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
})();


process.stdout.write(failures ? `\n${failures} failing\n` : "\nall passing\n");
process.exit(failures ? 1 : 0);
