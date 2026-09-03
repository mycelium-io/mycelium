// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import type { Memory } from "@/lib/api";
import {
  flattenMarkdown,
  memoryPreview,
  memoryTitle,
  memoryValueText,
  previewCardTop,
} from "@/lib/memory-preview";

const mem = (over: Partial<Memory>): Memory =>
  ({ key: "work/a-row", value: "", ...over }) as Memory;

describe("memoryValueText", () => {
  it("returns prose as written", () => {
    expect(memoryValueText("just prose")).toBe("just prose");
  });

  it("unwraps the text field of a structured value", () => {
    expect(memoryValueText({ text: "body", category: "decisions" })).toBe("body");
  });

  it("serialises a value with no text field", () => {
    expect(memoryValueText({ a: 1 })).toBe('{"a":1}');
  });
});

describe("flattenMarkdown", () => {
  it("strips heading, emphasis, and code decoration", () => {
    expect(flattenMarkdown("## Title\n\n**bold** and `code`")).toEqual([
      "Title",
      "",
      "bold and code",
    ]);
  });

  it("keeps link and wikilink text, drops the targets", () => {
    expect(flattenMarkdown("see [the docs](http://x) and [[context/scope]]")).toEqual([
      "see the docs and context/scope",
    ]);
  });

  it("uses the alias of a piped wikilink", () => {
    expect(flattenMarkdown("[[context/scope|the scope]]")).toEqual(["the scope"]);
  });

  it("marks list items with a bullet", () => {
    expect(flattenMarkdown("- one\n2. two")).toEqual(["• one", "• two"]);
  });

  it("drops fence markers but keeps the code lines", () => {
    expect(flattenMarkdown("```py\nx = 1\n```")).toEqual(["x = 1"]);
  });

  it("collapses blank runs and drops horizontal rules", () => {
    expect(flattenMarkdown("a\n\n\n---\n\nb\n\n")).toEqual(["a", "", "b"]);
  });
});

describe("memoryPreview", () => {
  it("reports an empty body rather than rendering a blank card", () => {
    expect(memoryPreview({ value: "   " }).empty).toBe(true);
  });

  it("clips at the line budget and flags the excerpt as truncated", () => {
    const body = Array.from({ length: 20 }, (_, i) => `line ${i}`).join("\n");
    const preview = memoryPreview({ value: body }, { maxLines: 3 });
    expect(preview.lines).toEqual(["line 0", "line 1", "line 2"]);
    expect(preview.truncated).toBe(true);
  });

  it("clips a long line at a word boundary", () => {
    const preview = memoryPreview({ value: "alpha beta gamma delta" }, { maxChars: 14 });
    expect(preview.lines).toEqual(["alpha beta…"]);
    expect(preview.truncated).toBe(true);
  });

  it("leaves a body inside both budgets whole", () => {
    const preview = memoryPreview({ value: "short body" });
    expect(preview.lines).toEqual(["short body"]);
    expect(preview.truncated).toBe(false);
  });

  it("falls back to content_text when the value carries no prose", () => {
    expect(memoryPreview({ value: "", content_text: "indexed text" }).lines).toEqual([
      "indexed text",
    ]);
  });
});

describe("previewCardTop", () => {
  it("centres the card on its row when there is room", () => {
    expect(previewCardTop(300, 22, 200, 900)).toBe(211);
  });

  it("keeps a card near the bottom edge inside the viewport", () => {
    expect(previewCardTop(860, 22, 200, 900, 12)).toBe(688);
  });

  it("keeps a card near the top edge inside the viewport", () => {
    expect(previewCardTop(0, 22, 200, 900, 12)).toBe(12);
  });

  it("pins to the top margin when the card is taller than the viewport", () => {
    expect(previewCardTop(300, 22, 800, 400, 12)).toBe(12);
  });
});

describe("memoryTitle", () => {
  it("uses an explicit title on a structured value", () => {
    expect(memoryTitle(mem({ value: { title: "Ship the board", status: "open" } }))).toBe(
      "Ship the board",
    );
  });

  it("takes the first line of a bare-string prose value", () => {
    expect(memoryTitle(mem({ value: "# Trim the install panel\nmore body" }))).toBe(
      "Trim the install panel",
    );
  });

  it("reads a prose value the store hands over as {text}", () => {
    // The API rebuilds prose into { text: … }; the title must be the first line,
    // never the key it happens to be filed under.
    const title = memoryTitle(mem({ key: "work/cutover", value: { text: "Cut over to Redis\nnotes" } }));
    expect(title).toBe("Cut over to Redis");
    expect(title).not.toBe("work/cutover");
  });

  it("falls back to content_text when the value carries no readable body", () => {
    expect(memoryTitle(mem({ key: "work/x", value: {}, content_text: "Do the thing" }))).toBe(
      "Do the thing",
    );
  });

  it("falls back to the key when there is nothing to read", () => {
    expect(memoryTitle(mem({ key: "work/empty", value: "" }))).toBe("work/empty");
  });
});
