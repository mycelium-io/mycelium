// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { mkdir, mkdtemp, rename, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { createSseDecoder } from "@/lib/sse";
import { themeFileEvents } from "@/lib/theme-files";

let home: string;
let dir: string;
let abort: AbortController;

/** Frames off the stream, counted as they arrive. */
function listen(res: Response) {
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  const decode = createSseDecoder();
  const seen = { frames: 0, ended: false };
  void (async () => {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      seen.frames += decode(decoder.decode(value, { stream: true })).length;
    }
    seen.ended = true;
  })().catch(() => {
    seen.ended = true;
  });
  return seen;
}

const until = async (check: () => boolean, ms = 3000) => {
  const end = Date.now() + ms;
  while (!check()) {
    if (Date.now() > end) throw new Error("timed out");
    await new Promise((r) => setTimeout(r, 20));
  }
};
const quiet = (ms = 400) => new Promise((r) => setTimeout(r, ms));

describe("themeFileEvents", () => {
  beforeEach(async () => {
    home = await mkdtemp(path.join(tmpdir(), "myc-home-"));
    dir = path.join(home, "themes");
    abort = new AbortController();
  });

  afterEach(async () => {
    abort.abort();
    await rm(home, { recursive: true, force: true });
  });

  it("says so once at the start, so a feed that (re)opens reads the files", async () => {
    const seen = listen(themeFileEvents(dir, abort.signal));
    await until(() => seen.frames === 1);
    await quiet();
    expect(seen.frames).toBe(1);
  });

  it("says so when `mycelium theme use` replaces theme.json", async () => {
    const seen = listen(themeFileEvents(dir, abort.signal));
    await until(() => seen.frames === 1);
    // The CLI's own way: a temp file beside it, then a rename.
    const tmp = path.join(home, ".theme.abc.json");
    await writeFile(tmp, '{"theme": "nord"}\n');
    await rename(tmp, path.join(home, "theme.json"));
    await until(() => seen.frames === 2);
    // One write is one frame, not one per file event.
    await quiet();
    expect(seen.frames).toBe(2);
  });

  it("says so when a theme is added, even to a folder made after it started", async () => {
    const seen = listen(themeFileEvents(dir, abort.signal));
    await until(() => seen.frames === 1);
    await mkdir(dir);
    await until(() => seen.frames === 2);
    await quiet();
    await writeFile(path.join(dir, "fern.json"), "{}");
    await until(() => seen.frames === 3);
  });

  it("says nothing about anything else in ~/.mycelium", async () => {
    const seen = listen(themeFileEvents(dir, abort.signal));
    await until(() => seen.frames === 1);
    await writeFile(path.join(home, "config.toml"), "x = 1\n");
    await quiet();
    expect(seen.frames).toBe(1);
  });

  it("ends when the app goes away", async () => {
    const seen = listen(themeFileEvents(dir, abort.signal));
    await until(() => seen.frames === 1);
    abort.abort();
    await until(() => seen.ended);
  });
});
