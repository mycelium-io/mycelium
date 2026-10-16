// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// Contract drift guard for the Hub page's editable settings (frontend side).
// The hub (services/hub_config.py) and the CLI (MyceliumConfig) assert the same
// file, so the page never draws a control for a key the hub would refuse.

import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { HUB_EDITABLE, editMode, parseNumber } from "@/lib/hub-settings";

const CONTRACT_PATH = path.resolve(__dirname, "../../../contracts/hub-settings.json");

const contract = JSON.parse(readFileSync(CONTRACT_PATH, "utf-8")) as {
  editable: Record<string, unknown>;
};

const editing = (over: Partial<Parameters<typeof editMode>[0] & object> = {}) => ({
  may_edit: true,
  reason: null,
  can_restart: true,
  app_owned: ["voice.enabled"],
  pending: [],
  values: {},
  ...over,
});

describe("hub settings contract", () => {
  it("edits exactly the contract's keys, the same way", () => {
    expect(HUB_EDITABLE).toEqual(contract.editable);
  });
});

describe("editMode", () => {
  it("is here for a key this caller may change, app for one the desktop app sets", () => {
    expect(editMode(editing(), "worker.tools")).toBe("here");
    expect(editMode(editing(), "voice.enabled")).toBe("app");
  });

  it("is no when the caller may not change the hub, or for a key the page can't change", () => {
    expect(editMode(editing({ may_edit: false }), "worker.tools")).toBe("no");
    expect(editMode(undefined, "worker.tools")).toBe("no");
    expect(editMode(editing(), "auth.enabled")).toBe("no");
  });
});

describe("parseNumber", () => {
  it("takes a number more than 0, and a whole one where it must be", () => {
    expect(parseNumber({ type: "number" }, "90.5")).toEqual({ value: 90.5 });
    expect(parseNumber({ type: "int" }, "30")).toEqual({ value: 30 });
    expect(parseNumber({ type: "int" }, "2.5")).toEqual({ error: "Type a whole number." });
    expect(parseNumber({ type: "number" }, "0")).toEqual({ error: "Type a number more than 0." });
    expect(parseNumber({ type: "number" }, "")).toEqual({ error: "Type a number." });
  });
});
