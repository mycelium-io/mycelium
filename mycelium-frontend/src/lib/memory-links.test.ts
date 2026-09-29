// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { isBrokenLinkError, linkErrorLabel } from "@/lib/memory-links";

describe("linkErrorLabel", () => {
  it("says a failure the way a person reads it", () => {
    expect(linkErrorLabel("not_found")).toBe("no such memory");
    expect(linkErrorLabel("cross_room")).toBe("cross-room links are not supported");
  });

  it("falls back to the code, or to 'broken' with none", () => {
    expect(linkErrorLabel("something_new")).toBe("something_new");
    expect(linkErrorLabel(null)).toBe("broken");
  });
});

describe("isBrokenLinkError", () => {
  it("counts a cross-room link as a limitation, not a defect", () => {
    expect(isBrokenLinkError("cross_room")).toBe(false);
    expect(isBrokenLinkError("not_found")).toBe(true);
  });
});
