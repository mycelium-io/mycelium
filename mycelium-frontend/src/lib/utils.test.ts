// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { cn } from "@/lib/utils";

describe("cn", () => {
  it("keeps one of this app's font sizes alongside a text colour", () => {
    // Both are `text-*`; only a merge that knows the size scale keeps both.
    expect(cn("text-label text-muted-foreground")).toBe("text-label text-muted-foreground");
    expect(cn("text-micro", "text-text")).toBe("text-micro text-text");
  });

  it("still collapses two sizes, or two colours, to the last one", () => {
    expect(cn("text-label text-body")).toBe("text-body");
    expect(cn("text-text text-muted-foreground")).toBe("text-muted-foreground");
  });
});
