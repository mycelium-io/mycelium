// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Cisco Systems, Inc. and its affiliates

import { describe, expect, it } from "vitest";
import { resolveMentions } from "../src/channel/mentions.js";

describe("resolveMentions", () => {
  const agents = ["julia-agent", "selina-agent", "arnold"];

  it("returns empty when content has no mentions", () => {
    expect(resolveMentions("hello world", agents)).toEqual([]);
  });

  it("returns empty when content is empty", () => {
    expect(resolveMentions("", agents)).toEqual([]);
  });

  it("returns empty when agents list is empty", () => {
    expect(resolveMentions("@julia-agent hi", [])).toEqual([]);
  });

  it("matches a single exact @handle", () => {
    expect(resolveMentions("@julia-agent ping", agents)).toEqual(["julia-agent"]);
  });

  it("matches handle at the start of content", () => {
    expect(resolveMentions("@arnold you there?", agents)).toEqual(["arnold"]);
  });

  it("matches handle at the end of content", () => {
    expect(resolveMentions("hey @julia-agent", agents)).toEqual(["julia-agent"]);
  });

  it("matches multiple handles in one message", () => {
    expect(resolveMentions("@julia-agent and @arnold please respond", agents)).toEqual([
      "julia-agent",
      "arnold",
    ]);
  });

  it("is case-insensitive", () => {
    expect(resolveMentions("@JULIA-AGENT hi", agents)).toEqual(["julia-agent"]);
    expect(resolveMentions("@Julia-Agent hi", agents)).toEqual(["julia-agent"]);
  });

  it("requires the @ prefix — bare handles do not match", () => {
    expect(resolveMentions("julia-agent do the thing", agents)).toEqual([]);
  });

  it("respects word boundaries — @julia-agent-bot does not match @julia-agent", () => {
    expect(resolveMentions("@julia-agent-bot", agents)).toEqual([]);
  });

  it("matches @julia-agent when followed by punctuation", () => {
    expect(resolveMentions("@julia-agent, please respond", agents)).toEqual(["julia-agent"]);
    expect(resolveMentions("@julia-agent!", agents)).toEqual(["julia-agent"]);
    expect(resolveMentions("@julia-agent.", agents)).toEqual(["julia-agent"]);
    expect(resolveMentions("(@julia-agent)", agents)).toEqual(["julia-agent"]);
  });

  it("matches @julia-agent when followed by whitespace variants", () => {
    expect(resolveMentions("@julia-agent\nhi", agents)).toEqual(["julia-agent"]);
    expect(resolveMentions("@julia-agent\thi", agents)).toEqual(["julia-agent"]);
  });

  it("does not match @julia when agent list has @julia-agent", () => {
    // @julia as a prefix of @julia-agent should not match a different agent
    // (this test guards against a bug where a shorter handle in the config
    //  would eat up matches for a longer one)
    expect(resolveMentions("@julia hi", agents)).toEqual([]);
  });

  it("matches when multiple candidate agents share a prefix", () => {
    const prefixAgents = ["agent", "agent-one", "agent-two"];
    expect(resolveMentions("@agent-one please", prefixAgents)).toEqual(["agent-one"]);
    expect(resolveMentions("@agent here", prefixAgents)).toEqual(["agent"]);
  });

  it("deduplicates if the same handle is mentioned twice", () => {
    // Current implementation returns the handle once since filter()
    // iterates cfg.agents; verify we don't accidentally return duplicates
    const result = resolveMentions("@julia-agent @julia-agent again", agents);
    expect(result).toEqual(["julia-agent"]);
  });
});
