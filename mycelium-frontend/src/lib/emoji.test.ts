// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { gemoji } from "gemoji";
import { beforeEach, describe, expect, it } from "vitest";

import {
  closedShortcode,
  inCode,
  mayHaveShortcode,
  readRecentEmoji,
  recordEmoji,
  replaceShortcodes,
  searchEmoji,
  shortcodeAt,
  tableFrom,
} from "@/lib/emoji";

const T = tableFrom(gemoji);

describe("shortcodeAt", () => {
  it("starts a shortcode at a : after whitespace or the line's start, from two letters", () => {
    expect(shortcodeAt("great :ta")).toEqual({ start: 6, query: "ta" });
    expect(shortcodeAt(":ta")).toEqual({ start: 0, query: "ta" });
    expect(shortcodeAt("ok\n:ta")).toEqual({ start: 3, query: "ta" });
    expect(shortcodeAt("nice :+1")).toEqual({ start: 5, query: "+1" });
    expect(shortcodeAt("great :t")).toBeNull();
  });

  it("leaves a : that means something else alone", () => {
    expect(shortcodeAt("at 12:30")).toBeNull();
    expect(shortcodeAt("see https://x")).toBeNull();
    expect(shortcodeAt("a: b")).toBeNull();
    expect(shortcodeAt("a:bc")).toBeNull();
    expect(shortcodeAt("ratio :30")).toBeNull();
    expect(shortcodeAt("run `foo :ta")).toBeNull();
    expect(shortcodeAt("```\nconst x = :ta")).toBeNull();
    // A closed span is prose again.
    expect(shortcodeAt("run `foo` :ta")).toEqual({ start: 10, query: "ta" });
  });
});

describe("inCode", () => {
  it("knows an open span or fence", () => {
    expect(inCode("a `b")).toBe(true);
    expect(inCode("a `b` c")).toBe(false);
    expect(inCode("```\nx")).toBe(true);
    expect(inCode("```\nx\n```\ny")).toBe(false);
  });
});

describe("closedShortcode", () => {
  it("finds a whole :name: that names an emoji", () => {
    expect(closedShortcode("so :tada:", T)).toEqual({ start: 3, emoji: "🎉", name: "tada" });
    expect(closedShortcode(":+1:", T)?.emoji).toBe("👍");
    expect(closedShortcode(":TADA:", T)?.emoji).toBe("🎉");
    expect(closedShortcode("so :nothing-here:", T)).toBeNull();
    expect(closedShortcode("12:30:", T)).toBeNull();
    expect(closedShortcode("`x :tada:", T)).toBeNull();
  });
});

describe("replaceShortcodes", () => {
  it("turns every known :name: into its emoji, outside code", () => {
    expect(replaceShortcodes("shipped :tada: :+1:", T)).toBe("shipped 🎉 👍");
    expect(replaceShortcodes(":tada:\nnext line :rocket:.", T)).toBe("🎉\nnext line 🚀.");
    expect(replaceShortcodes("keep :not_an_emoji_at_all: as typed", T)).toBe("keep :not_an_emoji_at_all: as typed");
    expect(replaceShortcodes("at 10:30:00 and a:tada:", T)).toBe("at 10:30:00 and a:tada:");
    expect(replaceShortcodes("run `echo :tada:` then :tada:", T)).toBe("run `echo :tada:` then 🎉");
    expect(replaceShortcodes("```\n:tada:\n```\n:tada:", T)).toBe("```\n:tada:\n```\n🎉");
  });

  it("says when there's nothing to turn", () => {
    expect(mayHaveShortcode("plain text, 12:30")).toBe(false);
    expect(mayHaveShortcode("yay :tada:")).toBe(true);
  });
});

describe("searchEmoji", () => {
  it("offers :tada for :ta, a shortcode that starts with the query first", () => {
    const found = searchEmoji(T, "ta");
    expect(found[0]).toMatchObject({ emoji: "🎉", name: "tada" });
    expect(found.every((m) => m.name.includes("ta") || T.entries.find((e) => e.emoji === m.emoji)?.tags.some((g) => g.startsWith("ta")))).toBe(true);
    expect(found.length).toBeLessThanOrEqual(8);
  });

  it("puts the recently used first among the matches", () => {
    expect(searchEmoji(T, "ta", ["🌮"])[0]).toMatchObject({ emoji: "🌮", name: "taco" });
    // A recent one that doesn't match isn't offered.
    expect(searchEmoji(T, "ta", ["👍"]).map((m) => m.emoji)).not.toContain("👍");
  });

  it("finds an emoji by its tag", () => {
    expect(searchEmoji(T, "hooray").map((m) => m.emoji)).toContain("🎉");
  });
});

describe("recently used", () => {
  beforeEach(() => window.localStorage.clear());

  it("is remembered newest first, once each", () => {
    recordEmoji("🎉");
    recordEmoji("👍");
    recordEmoji("🎉");
    expect(readRecentEmoji()).toEqual(["🎉", "👍"]);
  });

  it("reads as none when storage holds something else", () => {
    window.localStorage.setItem("mycelium.emoji.recent", "not json");
    expect(readRecentEmoji()).toEqual([]);
  });
});
