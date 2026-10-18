// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { afterEach, describe, expect, it, vi } from "vitest";
import { CHANNEL, clearOnScreen, onOnScreenChange, onScreenNow, setOnScreen, shows, type OnScreen } from "./on-screen";

const THREAD = "urn:ioc:mycelium:episode:sprint:t1";
const OTHER = "urn:ioc:mycelium:episode:sprint:t2";
const screen: OnScreen = { room: "sprint", panes: [CHANNEL, THREAD] };

describe("shows", () => {
  it("by thread: only a conversation that's in front", () => {
    expect(shows(screen, { room: "sprint", episode: THREAD }, "thread")).toBe(true);
    expect(shows(screen, { room: "sprint", episode: null }, "thread")).toBe(true);
    expect(shows(screen, { room: "sprint", episode: OTHER }, "thread")).toBe(false);
    expect(shows({ room: "sprint", panes: [THREAD] }, { room: "sprint" }, "thread")).toBe(false);
  });

  it("by room: anything in the room you have open", () => {
    expect(shows(screen, { room: "sprint", episode: OTHER }, "room")).toBe(true);
    expect(shows(screen, { room: "lobby" }, "room")).toBe(false);
  });

  it("never: nothing counts as in front", () => {
    expect(shows(screen, { room: "sprint", episode: THREAD }, "never")).toBe(false);
  });

  it("nothing is in front when no room is shown", () => {
    expect(shows(null, { room: "sprint" }, "room")).toBe(false);
  });
});

describe("setOnScreen", () => {
  afterEach(() => setOnScreen(null));

  it("tells listeners when what's shown changes, and only then", () => {
    const heard = vi.fn();
    const off = onOnScreenChange(heard);
    setOnScreen({ room: "sprint", panes: [CHANNEL] });
    setOnScreen({ room: "sprint", panes: [CHANNEL] });
    expect(heard).toHaveBeenCalledTimes(1);
    setOnScreen({ room: "sprint", panes: [CHANNEL, THREAD] });
    expect(heard).toHaveBeenCalledTimes(2);
    off();
  });

  it("a room leaving clears only itself", () => {
    setOnScreen({ room: "lobby", panes: [CHANNEL] });
    clearOnScreen("sprint");
    expect(onScreenNow()?.room).toBe("lobby");
    clearOnScreen("lobby");
    expect(onScreenNow()).toBeNull();
  });
});
