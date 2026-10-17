// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { excerptLength, plainInline, sayable, sentencesOf, speakable, splitSentences, MAX_SENTENCE } from "./speakable";

const said = (md: string) => sentencesOf(speakable(md)).map((s) => s.say);
const shown = (md: string) => sentencesOf(speakable(md)).map((s) => s.show);

describe("speakable", () => {
  it("takes the markup out and keeps the words", () => {
    expect(said("**Bold**, *italic*, _also_, ~~gone~~ and `code`.")).toEqual(["Bold, italic, also, gone and code."]);
  });

  it("reads a link by its text and a bare address by its site", () => {
    expect(said("See [the PR](https://github.com/x/y/pull/1) or https://www.example.com/a/b.")).toEqual([
      "See the PR or a link to example.com",
    ].map((s) => `${s}.`));
    // The popover still shows the address as written.
    expect(shown("Open https://example.com/x now.")).toEqual(["Open https://example.com/x now."]);
  });

  it("reads a handle without its @, shown as written", () => {
    const [s] = sentencesOf(speakable("@julia and @~schedule-ux, have a look."));
    expect(s.say).toBe("julia and schedule-ux, have a look.");
    expect(s.show).toBe("@julia and @~schedule-ux, have a look.");
  });

  it("reads a memory link by its name and drops a machine marker", () => {
    expect(said("Saved as [[work/speed-up-the-board]] and ![[uploads/shot-1.png]]. [[mycelium: accept]]")).toEqual([
      "Saved as speed up the board and shot 1.",
    ]);
    expect(said("See [[context/notes|the notes]].")).toEqual(["See the notes."]);
  });

  it("names a code block and a table instead of reading them", () => {
    const blocks = speakable("Here:\n\n```\nHTTP 500: timed out\n```\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\nThanks.");
    expect(blocks.map((b) => b.kind)).toEqual(["paragraph", "code", "table", "paragraph"]);
    expect(sentencesOf(blocks).map((s) => s.say)).toEqual(["Here:", "A code block.", "A table.", "Thanks."]);
    expect(blocks[1].raw).toBe("HTTP 500: timed out");
    expect(blocks[2].raw).toContain("| 1 | 2 |");
  });

  it("gives a heading and each list item a pause of their own", () => {
    expect(said("## What changed\n- the bell\n- the popover\n1. first")).toEqual([
      "What changed.",
      "the bell.",
      "the popover.",
      "first.",
    ]);
  });

  it("joins a paragraph's lines and splits it into sentences", () => {
    expect(said("One line\ncontinues here. A second one! And a third?")).toEqual([
      "One line continues here.",
      "A second one!",
      "And a third?",
    ]);
  });

  it("skips quotes' markers, rules and html", () => {
    expect(said("> quoted <b>text</b>\n\n---\n\nAfter.")).toEqual(["quoted text.", "After."]);
  });

  it("says nothing for a message with no words", () => {
    expect(speakable("[[mycelium: accept]]\n\n---")).toEqual([]);
  });
});

describe("splitSentences", () => {
  it("cuts a run-on line under the limit, at a comma where it can", () => {
    const long = Array.from({ length: 80 }, (_, i) => `part ${i}`).join(", ");
    const parts = splitSentences(long);
    expect(parts.length).toBeGreaterThan(1);
    for (const p of parts) expect(p.length).toBeLessThanOrEqual(MAX_SENTENCE);
    expect(parts.join(" ").replace(/\s+/g, " ")).toBe(long);
  });
});

describe("excerptLength", () => {
  it("reads the first paragraph and stops", () => {
    const blocks = speakable("First. Second.\n\nThird paragraph.");
    expect(excerptLength(blocks)).toBe(2);
  });

  it("reads a heading with the paragraph under it", () => {
    expect(excerptLength(speakable("# Title\n\nBody here.\n\nMore."))).toBe(2);
  });

  it("stops at about twenty seconds, at the end of a sentence", () => {
    const sentence = "This sentence has exactly ten words in it, all right.";
    const blocks = speakable(Array.from({ length: 8 }, () => sentence).join(" "));
    expect(excerptLength(blocks)).toBe(5);
  });
});

describe("plainInline and sayable", () => {
  it("leave plain text alone", () => {
    expect(plainInline("just words")).toBe("just words");
    expect(sayable("just words")).toBe("just words");
  });
});
