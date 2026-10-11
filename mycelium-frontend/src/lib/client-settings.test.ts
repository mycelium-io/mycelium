// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  __resetClientSettingsCache,
  clientSettingHref,
  getClientSetting,
  importClientSettings,
  resetClientSetting,
  setClientSetting,
  settingHref,
} from "@/lib/client-settings";
import { chordFor, setKeyOverrides } from "@/lib/keymap";

beforeEach(() => {
  window.localStorage.clear();
  __resetClientSettingsCache();
});

afterEach(() => {
  setKeyOverrides({});
});

describe("client settings", () => {
  it("reads defaults when nothing is stored", () => {
    expect(getClientSetting("general.send")).toBe("enter");
    expect(getClientSetting("general.time-zone")).toBe("");
    expect(getClientSetting("keys.overrides")).toEqual({});
  });

  it("stores only what differs from the default", () => {
    setClientSetting("general.send", "mod-enter");
    expect(JSON.parse(window.localStorage.getItem("mycelium.settings")!)).toEqual({ "general.send": "mod-enter" });
    resetClientSetting("general.send");
    expect(JSON.parse(window.localStorage.getItem("mycelium.settings")!)).toEqual({});
  });

  it("carries over the board's old time zone key, once", () => {
    window.localStorage.setItem("mycelium.board.tz", "Europe/Berlin");
    __resetClientSettingsCache();
    expect(getClientSetting("general.time-zone")).toBe("Europe/Berlin");
    setClientSetting("general.send", "mod-enter");
    expect(window.localStorage.getItem("mycelium.board.tz")).toBeNull();
    expect(JSON.parse(window.localStorage.getItem("mycelium.settings")!)["general.time-zone"]).toBe("Europe/Berlin");
  });

  it("drops a stored value of the wrong type", () => {
    window.localStorage.setItem(
      "mycelium.settings",
      JSON.stringify({ "general.send": "space", "keys.overrides": { "nav.home": "alt+h", "rail.memory": ["alt+y"] } }),
    );
    __resetClientSettingsCache();
    expect(getClientSetting("general.send")).toBe("enter");
    expect(getClientSetting("keys.overrides")).toEqual({ "rail.memory": ["alt+y"] });
  });

  it("applies changed shortcuts to the keymap", () => {
    expect(chordFor("rail.memory")).toBe("alt+m");
    setClientSetting("keys.overrides", { "rail.memory": ["alt+y"] });
    expect(chordFor("rail.memory")).toBe("alt+y");
  });

  it("imports an exported set", () => {
    const taken = importClientSettings({ "general.send": "mod-enter", stray: 1 });
    expect(taken["general.send"]).toBe("mod-enter");
    expect(getClientSetting("general.send")).toBe("mod-enter");
  });

  it("links to a setting on its page", () => {
    expect(clientSettingHref("general.send")).toBe("/settings/general#general.send");
    expect(settingHref("room", "worker-turns", "checkout")).toBe("/settings/room?room=checkout#worker-turns");
  });
});
