// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { mentionMode } from "@/lib/mentions";

describe("mentionMode", () => {
  it("says what @! and @~ do, and nothing for a plain @", () => {
    expect(mentionMode("@!")).toEqual({ label: "Interrupt", about: "stops a working agent", tone: "warn" });
    expect(mentionMode("@~")).toEqual({ label: "Silent", about: "names them without notifying", tone: "muted" });
    expect(mentionMode("@")).toBeNull();
    expect(mentionMode(undefined)).toBeNull();
  });
});
