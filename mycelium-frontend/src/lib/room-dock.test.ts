// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { afterEach, describe, expect, it } from "vitest";
import {
  forgetLayout,
  isClosable,
  loadLayout,
  loadView,
  memoryPanelId,
  panesInFront,
  parsePanelId,
  restorableLayout,
  saveLayout,
  saveView,
  threadPanelId,
} from "@/lib/room-dock";

const EPISODE = "urn:ioc:mycelium:episode:checkout:f1a5c7";
const THREAD = threadPanelId(EPISODE);
const MEMORY = memoryPanelId("work/x");

function layout(panels: Record<string, string>) {
  return {
    grid: {},
    panels: Object.fromEntries(Object.entries(panels).map(([id, component]) => [id, { id, contentComponent: component }])),
  };
}

describe("panesInFront", () => {
  it("names the conversations in front, the view's and each group's front tab, and nothing else", () => {
    expect(panesInFront(["channel", THREAD, memoryPanelId("decisions/x"), "board", undefined])).toEqual([
      "channel",
      EPISODE,
    ]);
    expect(panesInFront(["board"])).toEqual([]);
  });
});

describe("room dock panel ids", () => {
  it("names a memory and a thread by what they show, so one never opens twice", () => {
    expect(parsePanelId(memoryPanelId("decisions/cutover"))).toEqual({ kind: "memory", key: "decisions/cutover" });
    // A thread's URN has colons of its own; only the first one is the prefix.
    expect(parsePanelId(THREAD)).toEqual({ kind: "thread", episode: EPISODE });
    expect(parsePanelId("board")).toEqual({ kind: "board" });
  });

  it("draws nothing for an id it doesn't know", () => {
    expect(parsePanelId("terminal")).toBeNull();
    expect(parsePanelId("memory:")).toBeNull();
  });

  it("closes every tab, since a tab is something opened, and never a view", () => {
    expect(isClosable(MEMORY)).toBe(true);
    expect(isClosable(THREAD)).toBe(true);
    expect(isClosable("channel")).toBe(false);
    expect(isClosable("board")).toBe(false);
  });
});

describe("the room's view", () => {
  afterEach(() => window.localStorage.clear());

  it("is the Channel the first time, and the last one picked after that, per room", () => {
    expect(loadView("checkout")).toBe("channel");
    saveView("checkout", "board");
    expect(loadView("checkout")).toBe("board");
    expect(loadView("storefront")).toBe("channel");
  });

  it("reads as the Channel when what's stored isn't a view", () => {
    window.localStorage.setItem("mycelium.room-view.checkout", "terminal");
    expect(loadView("checkout")).toBe("channel");
  });
});

describe("a saved room layout", () => {
  afterEach(() => forgetLayout("checkout"));

  it("restores when every tab is something opened that this version draws", () => {
    expect(restorableLayout(layout({ [THREAD]: "thread", [MEMORY]: "memory" }))).toBe(true);
  });

  it("is dropped rather than half-restored when it names something else, or nothing", () => {
    expect(restorableLayout(layout({ [THREAD]: "thread", terminal: "terminal" }))).toBe(false);
    // A known id drawn by the wrong component is from some other version.
    expect(restorableLayout(layout({ [MEMORY]: "thread" }))).toBe(false);
    // A view isn't a tab any more.
    expect(restorableLayout(layout({ board: "board" }))).toBe(false);
    expect(restorableLayout(layout({}))).toBe(false);
    expect(restorableLayout(null)).toBe(false);
    expect(restorableLayout("nonsense")).toBe(false);
  });

  it("is kept per room in this browser", () => {
    const saved = layout({ [THREAD]: "thread" });
    saveLayout("checkout", saved);
    expect(loadLayout("checkout")).toEqual(saved);
    expect(loadLayout("storefront")).toBeNull();
  });

  it("loads a layout saved with the views as tabs without them, keeping what was opened", () => {
    const saved = {
      grid: { root: { type: "leaf", data: { views: ["channel", "board", MEMORY], activeView: "board" } } },
      panels: {
        channel: { id: "channel", contentComponent: "channel", title: "Channel" },
        board: { id: "board", contentComponent: "board", title: "Board" },
        [MEMORY]: { id: MEMORY, contentComponent: "memory", title: "x", params: { key: "work/x" } },
      },
    };
    saveLayout("checkout", saved);
    const loaded = loadLayout("checkout") as typeof saved & { panels: Record<string, unknown> };
    expect(restorableLayout(loaded)).toBe(true);
    expect(Object.keys(loaded.panels)).toEqual([MEMORY]);
    // A view was in front, so its group now shows what's left.
    expect(loaded.grid.root.data).toEqual({ views: [MEMORY], activeView: MEMORY });
  });

  for (const retired of ["raw", "network"]) {
    it(`loads a layout saved with the ${retired} tab without it`, () => {
      const saved = {
        grid: { root: { type: "leaf", data: { views: [retired, THREAD], activeView: retired } } },
        panels: {
          [retired]: { id: retired, contentComponent: retired, title: "Raw messages" },
          [THREAD]: { id: THREAD, contentComponent: "thread", params: { episode: EPISODE } },
        },
      };
      saveLayout("checkout", saved);
      const loaded = loadLayout("checkout") as typeof saved & { panels: Record<string, unknown> };
      expect(Object.keys(loaded.panels)).toEqual([THREAD]);
    });
  }

  it("starts with no tabs when a group held only views", () => {
    const saved = {
      grid: {
        root: {
          type: "branch",
          data: [
            { type: "leaf", data: { views: ["channel", "board"], activeView: "channel" }, size: 600 },
            { type: "leaf", data: { views: [THREAD], activeView: THREAD }, size: 400 },
          ],
        },
      },
      panels: {
        channel: { id: "channel", contentComponent: "channel", title: "Channel" },
        board: { id: "board", contentComponent: "board", title: "Board" },
        [THREAD]: { id: THREAD, contentComponent: "thread", params: { episode: EPISODE } },
      },
    };
    saveLayout("checkout", saved);
    expect(loadLayout("checkout")).toBeNull();
  });

  it("leaves a memory tab for a key named after a view or a retired tab alone", () => {
    for (const key of ["raw", "network", "board"]) {
      const id = memoryPanelId(key);
      const saved = {
        grid: { root: { type: "leaf", data: { views: [id], activeView: id } } },
        panels: { [id]: { id, contentComponent: "memory", title: key, params: { key } } },
      };
      saveLayout("checkout", saved);
      expect(loadLayout("checkout")).toEqual(saved);
    }
  });

  it("reads as none when what is stored isn't JSON", () => {
    window.localStorage.setItem("mycelium.dock.checkout", "{not json");
    expect(loadLayout("checkout")).toBeNull();
  });
});
