// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { afterEach, describe, expect, it } from "vitest";
import {
  forgetLayout,
  isClosable,
  loadLayout,
  memoryPanelId,
  parsePanelId,
  restorableLayout,
  saveLayout,
  threadPanelId,
} from "@/lib/room-dock";

const EPISODE = "urn:ioc:mycelium:episode:checkout:f1a5c7";

function layout(panels: Record<string, string>) {
  return {
    grid: {},
    panels: Object.fromEntries(Object.entries(panels).map(([id, component]) => [id, { id, contentComponent: component }])),
  };
}

describe("room dock panel ids", () => {
  it("names a memory and a thread by what they show, so one never opens twice", () => {
    expect(parsePanelId(memoryPanelId("decisions/cutover"))).toEqual({ kind: "memory", key: "decisions/cutover" });
    // A thread's URN has colons of its own; only the first one is the prefix.
    expect(parsePanelId(threadPanelId(EPISODE))).toEqual({ kind: "thread", episode: EPISODE });
    expect(parsePanelId("board")).toEqual({ kind: "board" });
  });

  it("draws nothing for an id it doesn't know", () => {
    expect(parsePanelId("terminal")).toBeNull();
    expect(parsePanelId("memory:")).toBeNull();
  });

  it("keeps the Channel open: every other tab closes", () => {
    expect(isClosable("channel")).toBe(false);
    expect(isClosable("board")).toBe(true);
    expect(isClosable(memoryPanelId("work/x"))).toBe(true);
  });
});

describe("a saved room layout", () => {
  afterEach(() => forgetLayout("checkout"));

  it("restores when every tab is one this version draws, the Channel among them", () => {
    expect(
      restorableLayout(
        layout({ channel: "channel", board: "board", [threadPanelId(EPISODE)]: "thread", [memoryPanelId("work/x")]: "memory" }),
      ),
    ).toBe(true);
  });

  it("is dropped rather than half-restored when it names something else", () => {
    expect(restorableLayout(layout({ channel: "channel", terminal: "terminal" }))).toBe(false);
    // A known id drawn by the wrong component is from some other version.
    expect(restorableLayout(layout({ channel: "channel", board: "memory" }))).toBe(false);
    // The room's home has to be in it.
    expect(restorableLayout(layout({ board: "board" }))).toBe(false);
    expect(restorableLayout(null)).toBe(false);
    expect(restorableLayout("nonsense")).toBe(false);
  });

  it("is kept per room in this browser", () => {
    const saved = layout({ channel: "channel" });
    saveLayout("checkout", saved);
    expect(loadLayout("checkout")).toEqual(saved);
    expect(loadLayout("storefront")).toBeNull();
  });

  it("reads as none when what is stored isn't JSON", () => {
    window.localStorage.setItem("mycelium.dock.checkout", "{not json");
    expect(loadLayout("checkout")).toBeNull();
  });
});
