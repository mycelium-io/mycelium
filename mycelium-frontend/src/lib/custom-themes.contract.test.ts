// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// Contract drift guard for custom themes (frontend side). The hub's themes
// folder (services/themes.py) asserts the same file, so a theme an agent adds
// with `mycelium theme add` is one this app can paint, and every built-in
// theme `mycelium theme use` may name is one this app ships.

import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { MAY_BE_TRANSLUCENT, NAME_MAX, OPTIONAL_COLORS, REQUIRED_COLORS } from "@/lib/custom-themes";
import { THEMES } from "@/lib/themes";

const contract = JSON.parse(
  readFileSync(path.resolve(__dirname, "../../../contracts/custom-theme.json"), "utf-8"),
) as {
  name_max: number;
  required: string[];
  optional: string[];
  translucent: string[];
  builtin: { id: string; label: string; mode: string }[];
};

describe("custom themes match contracts/custom-theme.json", () => {
  it("takes the same colors, by the same rules", () => {
    expect([...REQUIRED_COLORS]).toEqual(contract.required);
    expect([...OPTIONAL_COLORS]).toEqual(contract.optional);
    expect([...MAY_BE_TRANSLUCENT].sort()).toEqual([...contract.translucent].sort());
    expect(NAME_MAX).toBe(contract.name_max);
  });

  it("ships the built-in themes the hub can name", () => {
    expect(THEMES.map(({ id, label, mode }) => ({ id, label, mode }))).toEqual(contract.builtin);
  });
});
