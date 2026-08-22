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
import { backdrop, palette } from "../src/theme.mjs";
import { CANVAS_VARS, networkDocument } from "../src/mycelial.mjs";
import { cardDocument } from "../src/card.mjs";

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

test("a card grows an artwork layer only when there is artwork", () => {
  assert.ok(!cardDocument("hi", { backdrop: "ink" }).includes('id="art"'));
  const art = cardDocument("hi", { backdrop: "mycelial", art: "url(data:image/png;base64,AA) center/cover" });
  assert.ok(art.includes('id="art"'));
  assert.ok(art.includes("image-rendering:pixelated"), "the cells must not blur when upscaled");
});

process.stdout.write(failures ? `\n${failures} failing\n` : "\nall passing\n");
process.exit(failures ? 1 : 0);
