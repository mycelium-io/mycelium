// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// Contract drift guard for room settings (frontend side). The hub checks every
// write to settings/ against contracts/room-settings.json; the settings page
// draws its controls from this copy, so a setting the hub added, renamed or
// gave new choices to would otherwise show the wrong control or none.

import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import type { RoomSetting } from "@/lib/api";
import { boardMovesInChat, ROOM_SETTINGS } from "@/lib/room-settings";

const CONTRACT_PATH = path.resolve(__dirname, "../../../contracts/room-settings.json");

const contract = JSON.parse(readFileSync(CONTRACT_PATH, "utf-8")) as {
  settings: { id: string; kind: string; options?: string[]; default?: string[] }[];
};

describe("room settings contract", () => {
  it("lists every setting the hub has, in its order", () => {
    expect(ROOM_SETTINGS.map((s) => s.id)).toEqual(contract.settings.map((s) => s.id));
  });

  it("matches each setting's kind, choices and default", () => {
    for (const ours of ROOM_SETTINGS) {
      const theirs = contract.settings.find((s) => s.id === ours.id)!;
      expect(ours.kind).toBe(theirs.kind);
      expect(ours.options ?? undefined).toEqual(theirs.options);
      expect(ours.default ?? undefined).toEqual(theirs.default);
    }
  });

  it("labels every choice of a set", () => {
    for (const s of ROOM_SETTINGS) {
      for (const option of s.options ?? []) expect(s.optionLabels?.[option]).toBeTruthy();
    }
  });
});

describe("boardMovesInChat", () => {
  it("is the default before the settings load", () => {
    expect([...boardMovesInChat([])]).toEqual(["filed", "resolved"]);
  });

  it("is the room's choice once they have", () => {
    const setting = { id: "chat-board-moves", value: ["claimed", "blocked"] } as RoomSetting;
    expect([...boardMovesInChat([setting])]).toEqual(["claimed", "blocked"]);
  });
});
