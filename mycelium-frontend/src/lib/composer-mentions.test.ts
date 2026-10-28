// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { composerMentions } from "@/lib/composer-mentions";

const members = new Set(["eng", "product", "julia", "conductor"]);

/** Each `@word` as the text it covers, with whether it reaches a member. */
const read = (text: string) =>
  composerMentions(text, members).map((m) => [text.slice(m.start, m.end), m.kind, m.resolved]);

describe("composerMentions", () => {
  it("resolves a member's handle with each sigil", () => {
    expect(read("@eng @~product @!julia")).toEqual([
      ["@eng", "mention", true],
      ["@~product", "silent", true],
      ["@!julia", "interrupt", true],
    ]);
  });

  it("leaves a handle that isn't a member unresolved", () => {
    expect(read("@engg and @~nobody")).toEqual([
      ["@engg", "mention", false],
      ["@~nobody", "silent", false],
    ]);
  });

  it("drops back to unresolved when a member's handle is edited away", () => {
    expect(read("@eng")[0][2]).toBe(true);
    expect(read("@en")[0][2]).toBe(false);
    expect(read("@engineering")[0][2]).toBe(false);
  });

  it("matches a handle whatever its case", () => {
    expect(read("@Julia")).toEqual([["@Julia", "mention", true]]);
  });

  it("stops a handle at punctuation", () => {
    expect(read("thanks @eng, and (@julia)")).toEqual([
      ["@eng", "mention", true],
      ["@julia", "mention", true],
    ]);
  });

  it("never resolves the @ of an email address, even a member's", () => {
    expect(read("write to julia@eng.example")).toEqual([["@eng", "mention", false]]);
  });

  it("skips a handle quoted as code", () => {
    expect(read("run `@eng` then ask @eng")).toEqual([["@eng", "mention", true]]);
    expect(read("```\n@eng\n```")).toEqual([]);
  });

  it("finds nothing in a lone @ still being typed", () => {
    expect(read("hey @")).toEqual([]);
  });
});
