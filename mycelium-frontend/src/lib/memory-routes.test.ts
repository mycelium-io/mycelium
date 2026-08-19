// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { encodeMemoryKeyPath, memoryHref, parseMemoryKeyParam } from "@/lib/memory-routes";

describe("encodeMemoryKeyPath", () => {
  it("encodes each slash segment separately", () => {
    expect(encodeMemoryKeyPath("decisions/db choice")).toBe(
      "decisions/db%20choice",
    );
  });

  it("round-trips through parseMemoryKeyParam", () => {
    const key = "log/episodes/a1:b2";
    const segments = encodeMemoryKeyPath(key).split("/");
    expect(parseMemoryKeyParam(segments)).toBe(key);
  });
});

describe("memoryHref", () => {
  it("builds a catch-all path for slash keys", () => {
    expect(memoryHref("demo", "context/overview")).toBe("/room/demo/memory/context/overview");
  });

  it("encodes room names with spaces", () => {
    expect(memoryHref("atlas migration", "plan/title")).toBe(
      "/room/atlas%20migration/memory/plan/title",
    );
  });
});
