// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { afterEach, describe, expect, it, vi } from "vitest";
import {
  BUILT_IN,
  STORAGE_KEY,
  deleteExample,
  loadSaved,
  saveExample,
} from "@/lib/instruction-examples";

afterEach(() => {
  window.localStorage.clear();
  vi.restoreAllMocks();
});

describe("instruction examples", () => {
  it("ships a few to start from", () => {
    expect(BUILT_IN.map((e) => e.name)).toContain("reviewer");
    expect(BUILT_IN.every((e) => e.text.length > 0)).toBe(true);
  });

  it("keeps saved ones in this browser, one per name", () => {
    saveExample(" triager ", "Sort new issues.");
    saveExample("triager", "Sort new issues by area.");
    expect(loadSaved()).toEqual([{ name: "triager", text: "Sort new issues by area.", saved: true }]);
    expect(JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "")).toEqual([
      { name: "triager", text: "Sort new issues by area." },
    ]);
  });

  it("deletes a saved one", () => {
    saveExample("a", "one");
    saveExample("b", "two");
    expect(deleteExample("a").map((e) => e.name)).toEqual(["b"]);
    expect(loadSaved().map((e) => e.name)).toEqual(["b"]);
  });

  it("reads nothing from storage it can't use", () => {
    window.localStorage.setItem(STORAGE_KEY, "{not json");
    expect(loadSaved()).toEqual([]);
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify([{ name: "", text: "x" }, 3]));
    expect(loadSaved()).toEqual([]);
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(loadSaved()).toEqual([]);
  });
});
