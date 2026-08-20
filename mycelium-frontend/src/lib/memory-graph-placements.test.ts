// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { loadPlacements, savePlacements, storageKeyFor } from "@/lib/memory-graph-placements";

/** In-memory `localStorage` stub for tests when the environment provides no usable storage API. */
function fakeStorage(seed: Record<string, string> = {}) {
  const data = new Map(Object.entries(seed));
  return {
    data,
    getItem: vi.fn((k: string) => data.get(k) ?? null),
    setItem: vi.fn((k: string, v: string) => void data.set(k, v)),
    removeItem: vi.fn((k: string) => void data.delete(k)),
  };
}

const ALL = new Set(["context/goal", "decisions/cutover"]);

describe("memory graph placements", () => {
  afterEach(() => vi.unstubAllGlobals());

  describe("round trip", () => {
    beforeEach(() => vi.stubGlobal("localStorage", fakeStorage()));

    it("gives back what was saved for the same room", () => {
      savePlacements("atlas", { "context/goal": { x: 12, y: 34 } });
      expect(loadPlacements("atlas", ALL)).toEqual({ "context/goal": { x: 12, y: 34 } });
    });

    it("keeps rooms apart", () => {
      savePlacements("atlas", { "context/goal": { x: 1, y: 2 } });
      expect(loadPlacements("other", ALL)).toEqual({});
    });

    it("removes the entry rather than storing an empty one", () => {
      const store = fakeStorage();
      vi.stubGlobal("localStorage", store);

      savePlacements("atlas", { "context/goal": { x: 1, y: 2 } });
      savePlacements("atlas", {});

      expect(store.removeItem).toHaveBeenCalledWith(storageKeyFor("atlas"));
      expect(store.data.has(storageKeyFor("atlas"))).toBe(false);
    });
  });

  describe("pruning", () => {
    it("drops a position for a memory that no longer exists", () => {
      // The whole reason pruning happens on read: a renamed or deleted memory
      // would otherwise strand a position nothing can ever reach again.
      vi.stubGlobal("localStorage", fakeStorage());
      savePlacements("atlas", {
        "context/goal": { x: 1, y: 2 },
        "context/deleted": { x: 9, y: 9 },
      });

      expect(loadPlacements("atlas", ALL)).toEqual({ "context/goal": { x: 1, y: 2 } });
    });

    it("forgets the stranded entry once the pruned map is saved back", () => {
      const store = fakeStorage();
      vi.stubGlobal("localStorage", store);
      savePlacements("atlas", { "context/goal": { x: 1, y: 2 }, "gone": { x: 9, y: 9 } });

      savePlacements("atlas", loadPlacements("atlas", ALL));

      expect(JSON.parse(store.data.get(storageKeyFor("atlas"))!).positions).toEqual({
        "context/goal": { x: 1, y: 2 },
      });
    });
  });

  describe("degrading safely", () => {
    it("ignores unparseable JSON", () => {
      vi.stubGlobal("localStorage", fakeStorage({ [storageKeyFor("atlas")]: "{not json" }));
      expect(loadPlacements("atlas", ALL)).toEqual({});
    });

    it("ignores a payload written by a different schema version", () => {
      const raw = JSON.stringify({ v: 99, positions: { "context/goal": { x: 1, y: 2 } } });
      vi.stubGlobal("localStorage", fakeStorage({ [storageKeyFor("atlas")]: raw }));
      expect(loadPlacements("atlas", ALL)).toEqual({});
    });

    it("drops a coordinate that isn't a finite number", () => {
      const raw = JSON.stringify({
        v: 1,
        positions: {
          "context/goal": { x: 1, y: 2 },
          "decisions/cutover": { x: null, y: "nope" },
        },
      });
      vi.stubGlobal("localStorage", fakeStorage({ [storageKeyFor("atlas")]: raw }));
      expect(loadPlacements("atlas", ALL)).toEqual({ "context/goal": { x: 1, y: 2 } });
    });

    it("survives a storage object whose methods are missing", () => {
      vi.stubGlobal("localStorage", {});
      expect(loadPlacements("atlas", ALL)).toEqual({});
      expect(() => savePlacements("atlas", { a: { x: 1, y: 2 } })).not.toThrow();
    });

    it("survives a store that throws on write (quota, private mode)", () => {
      vi.stubGlobal("localStorage", {
        getItem: () => null,
        setItem: () => {
          throw new Error("QuotaExceededError");
        },
        removeItem: () => {},
      });
      expect(() => savePlacements("atlas", { a: { x: 1, y: 2 } })).not.toThrow();
    });
  });
});
