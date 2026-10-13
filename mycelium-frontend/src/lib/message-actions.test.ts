// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { appendToDraft, quoteText, replyText, taskBody, taskTitle } from "./message-actions";
import { parseInterruptMentions, parseMentions } from "./mentions";

describe("quoteText", () => {
  it("quotes every line and names the sender silently on the first", () => {
    expect(quoteText("merged #499\n\nstarting on apple pay", "builder")).toBe(
      "> @~builder: merged #499\n>\n> starting on apple pay\n\n",
    );
  });

  it("notifies nobody it quotes: every mention in it is made silent", () => {
    const quote = quoteText("@builder @reviewer we need a day\n@aligner run it (@!coder stop)", "julia");
    expect(quote).toBe("> @~julia: @~builder @~reviewer we need a day\n> @~aligner run it (@~coder stop)\n\n");
    expect(parseMentions(quote)).toEqual([]);
    expect(parseInterruptMentions(quote)).toEqual([]);
  });

  it("leaves what isn't a mention alone", () => {
    expect(quoteText("mail a@b.com, already @~sam", "julia")).toBe("> @~julia: mail a@b.com, already @~sam\n\n");
  });
});

describe("appendToDraft", () => {
  it("starts an empty draft with the text", () => {
    expect(appendToDraft("", replyText("builder"))).toBe("@builder ");
    expect(appendToDraft("  \n", replyText("builder"))).toBe("@builder ");
  });

  it("carries a mention on after what is typed", () => {
    expect(appendToDraft("thanks", replyText("builder"))).toBe("thanks @builder ");
    expect(appendToDraft("thanks ", replyText("builder"))).toBe("thanks @builder ");
  });

  it("adds nothing when the draft already mentions them", () => {
    expect(appendToDraft("@builder can you", replyText("builder"))).toBe("@builder can you");
    expect(appendToDraft("@builder-2 can you", replyText("builder"))).toBe("@builder-2 can you @builder ");
  });

  it("sets a quote apart as its own block", () => {
    const quote = quoteText("ok", "reviewer");
    expect(appendToDraft("see this", quote)).toBe(`see this\n\n${quote}`);
    expect(appendToDraft("see this\n", quote)).toBe(`see this\n\n${quote}`);
    expect(appendToDraft(quote, quote)).toBe(quote + quote);
  });
});

describe("taskTitle", () => {
  it("takes the first line of words, without markdown or sigils", () => {
    expect(taskTitle("\n## **Ship** the [[context/goals]] fix\nmore")).toBe("Ship the context/goals fix");
    expect(taskTitle("> @builder can you look at `checkout`?")).toBe("builder can you look at checkout?");
    expect(taskTitle("- see [the PR](https://x.test/1)")).toBe("see the PR");
  });

  it("cuts a long line at a word", () => {
    const title = taskTitle(`${"word ".repeat(30)}end`);
    expect(title.endsWith("word…")).toBe(true);
    expect(title.length).toBeLessThanOrEqual(81);
  });

  it("has something to say for a message with no words", () => {
    expect(taskTitle("  \n ")).toBe("Follow up on a message");
  });
});

describe("taskBody", () => {
  it("quotes the message and links back to it", () => {
    expect(taskBody("a\n\nb", "builder", "http://hub/room/r?focus=message%3A1")).toBe(
      "> a\n>\n> b\n\nFrom [a message](http://hub/room/r?focus=message%3A1) by @~builder in the channel.\n",
    );
    expect(taskBody("a", "builder", null)).toBe("> a\n\nFrom a message by @~builder in the channel.\n");
  });

  it("makes the quoted mentions silent", () => {
    expect(taskBody("@aligner run it", "builder", null)).toBe("> @~aligner run it\n\nFrom a message by @~builder in the channel.\n");
  });
});
