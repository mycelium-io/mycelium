// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import type { PresenceMember } from "@/lib/api";
import { memberState, wantsScreen, type MemberKind } from "@/lib/agent-card";

const herdr = (status: string, extra: Partial<PresenceMember> = {}): PresenceMember => ({
  handle: "builder",
  kind: "herdr",
  last_seen: null,
  status,
  ...extra,
});

describe("memberState", () => {
  it("reads an agent's state from its presence", () => {
    expect(memberState("agent", herdr("working")).key).toBe("working");
    expect(memberState("agent", herdr("blocked")).key).toBe("waiting");
    expect(memberState("agent", herdr("idle")).key).toBe("idle");
    expect(memberState("agent", undefined).key).toBe("not_running");
  });

  it("says can't reply before anything else, once the runner says so", () => {
    expect(memberState("agent", herdr("working", { can_reply: false })).key).toBe("cant_reply");
  });

  it("never says can't reply while nothing reports it", () => {
    expect(memberState("agent", herdr("working", { can_reply: null })).key).toBe("working");
    expect(memberState("agent", herdr("blocked")).key).toBe("waiting");
  });

  it("gives a person and an engine their own words", () => {
    expect(memberState("person", herdr("idle")).word).toBe("Here");
    expect(memberState("person", undefined).word).toBe("Away");
    expect(memberState("engine", undefined, "conductor").word).toBe("conductor");
  });
});

describe("wantsScreen", () => {
  const asks = (kind: MemberKind, presence?: PresenceMember) => wantsScreen(kind, memberState(kind, presence));

  it("asks for an agent's screen only while it says something", () => {
    expect(asks("agent", herdr("working"))).toBe(true);
    expect(asks("agent", herdr("blocked"))).toBe(true);
    expect(asks("agent", herdr("idle", { can_reply: false }))).toBe(true);
    expect(asks("agent", herdr("idle"))).toBe(false);
    expect(asks("agent", undefined)).toBe(false);
  });

  it("never asks for a person's or an engine's", () => {
    expect(asks("person", herdr("working"))).toBe(false);
    expect(asks("engine", herdr("working"))).toBe(false);
  });
});
