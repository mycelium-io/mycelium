// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// Contract drift guard for the shared "raise-up" whitelist (frontend side).
//
// The CLI (mycelium-cli/src/mycelium/commands/room.py) carries its own copy of
// this list so the thin `uv tool` CLI need not import the frontend, and the
// frontend carries its own copy so its Docker build (context: mycelium-frontend/
// only) need not reach outside its own tree. This test freezes the shared
// whitelist in contracts/channel-surface.json at the repo root and asserts the
// frontend's copy reproduces it exactly. The CLI suite asserts its own copy
// against the same file (mycelium-cli/tests/test_channel_surface_contract.py). One
// frozen source, two asserters — so neither copy can drift without turning a
// fast unit gate red.

import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { RAISE_UP_TYPES } from "@/components/event-stream";

const CONTRACT_PATH = path.resolve(__dirname, "../../../contracts/channel-surface.json");

function contract(): { raise_up_types: string[] } {
  return JSON.parse(readFileSync(CONTRACT_PATH, "utf-8"));
}

describe("raise-up whitelist contract", () => {
  it("matches contracts/channel-surface.json byte-for-byte", () => {
    const g = contract();
    expect(new Set(RAISE_UP_TYPES)).toEqual(new Set(g.raise_up_types));
    expect(RAISE_UP_TYPES.length).toBe(g.raise_up_types.length);
  });
});
