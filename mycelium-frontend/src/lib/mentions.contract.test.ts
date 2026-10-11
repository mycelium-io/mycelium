// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// Contract drift guard for @-mentions (frontend side). The hub parses message
// text for mentions too (persister.parse_mentions / parse_silent_mentions), and
// both assert contracts/mentions.json, so the app never rings for an `@~handle`
// the hub left silent, or draws one the hub woke someone for as silent.

import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import {
  INTERRUPT_MENTION_SIGIL,
  MENTION_SIGIL,
  SILENT_MENTION_SIGIL,
  parseInterruptMentions,
  parseMentions,
  parseSilentMentions,
} from "@/lib/mentions";

const CONTRACT_PATH = path.resolve(__dirname, "../../../contracts/mentions.json");

const contract = JSON.parse(readFileSync(CONTRACT_PATH, "utf-8")) as {
  sigils: { mention: string; silent: string; interrupt: string };
  cases: { text: string; mentions: string[]; silent: string[]; interrupt: string[] }[];
};

describe("mentions contract", () => {
  it("uses the contract's sigils", () => {
    expect({
      mention: MENTION_SIGIL,
      silent: SILENT_MENTION_SIGIL,
      interrupt: INTERRUPT_MENTION_SIGIL,
    }).toEqual(contract.sigils);
  });

  it.each(contract.cases)("parses $text", ({ text, mentions, silent, interrupt }) => {
    expect(parseMentions(text)).toEqual(mentions);
    expect(parseSilentMentions(text)).toEqual(silent);
    expect(parseInterruptMentions(text)).toEqual(interrupt);
  });
});
