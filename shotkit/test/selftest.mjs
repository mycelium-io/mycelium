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
import { parseAction } from "../src/actions.mjs";
import { palette } from "../src/theme.mjs";
import { encodeArgs, jpegSize } from "../src/encode.mjs";
import { parseZoom } from "../src/video.mjs";

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

process.stdout.write(failures ? `\n${failures} failing\n` : "\nall passing\n");
process.exit(failures ? 1 : 0);
