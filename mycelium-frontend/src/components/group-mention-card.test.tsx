// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// "Send silently" turns the groups in a message silent, and nothing else: a
// member whose handle starts like a group, and anything inside code, stay as
// written.

import { describe, expect, it } from "vitest";
import { silenceGroups } from "@/components/group-mention-card";
import { parseGroupMentions } from "@/lib/mentions";

describe("silenceGroups", () => {
  it("silences each group, in any form and letter case", () => {
    expect(silenceGroups("@all please look, and @!here too")).toBe("@~all please look, and @~here too");
    expect(silenceGroups("@All please look")).toBe("@~All please look");
    expect(silenceGroups("@~here already")).toBe("@~here already");
  });

  it("leaves a member called here-team as a mention", () => {
    expect(silenceGroups("@here-team ok")).toBe("@here-team ok");
    expect(silenceGroups("@here and @here-team")).toBe("@~here and @here-team");
  });

  it("leaves a group written inside code alone", () => {
    expect(silenceGroups("type `@all` to reach everyone, @all")).toBe("type `@all` to reach everyone, @~all");
  });

  it("leaves an email address alone", () => {
    expect(silenceGroups("mail me at sam@all.example")).toBe("mail me at sam@all.example");
  });
});

describe("parseGroupMentions", () => {
  it("reads a group in any letter case", () => {
    expect(parseGroupMentions("@All please look")).toEqual({ all: "mention" });
    expect(parseGroupMentions("@!HERE stop")).toEqual({ here: "interrupt" });
  });
});
