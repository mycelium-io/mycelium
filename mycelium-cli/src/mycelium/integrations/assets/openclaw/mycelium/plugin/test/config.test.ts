// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

import { describe, expect, it } from "vitest";
import { readChannelConfig, readChannelConfigs } from "../src/config.js";

describe("readChannelConfig", () => {
  it("returns null for null input", () => {
    expect(readChannelConfig(null)).toBeNull();
  });

  it("returns null for empty object", () => {
    expect(readChannelConfig({})).toBeNull();
  });

  it("returns null when channels section is missing", () => {
    expect(readChannelConfig({ agents: { list: [] } })).toBeNull();
  });

  it("returns null when channels.mycelium-room is missing", () => {
    expect(readChannelConfig({ channels: { discord: {} } })).toBeNull();
  });

  it("returns null when backendUrl is missing", () => {
    expect(
      readChannelConfig({
        channels: { "mycelium-room": { room: "my-project" } },
      }),
    ).toBeNull();
  });

  it("returns null when room is missing", () => {
    expect(
      readChannelConfig({
        channels: { "mycelium-room": { backendUrl: "http://localhost:8001" } },
      }),
    ).toBeNull();
  });

  it("returns null when channel is explicitly disabled", () => {
    expect(
      readChannelConfig({
        channels: {
          "mycelium-room": {
            enabled: false,
            backendUrl: "http://localhost:8001",
            room: "my-project",
            agents: ["a"],
          },
        },
      }),
    ).toBeNull();
  });

  it("parses a fully-configured channel", () => {
    const cfg = readChannelConfig({
      channels: {
        "mycelium-room": {
          enabled: true,
          backendUrl: "http://localhost:8001",
          room: "my-project",
          agents: ["julia-agent", "selina-agent"],
          requireMention: true,
        },
      },
    });
    expect(cfg).toEqual({
      backendUrl: "http://localhost:8001",
      room: "my-project",
      agents: ["julia-agent", "selina-agent"],
      requireMention: true,
    });
  });

  it("strips a trailing slash from backendUrl", () => {
    const cfg = readChannelConfig({
      channels: {
        "mycelium-room": {
          backendUrl: "http://localhost:8001/",
          room: "r",
          agents: ["a"],
        },
      },
    });
    expect(cfg?.backendUrl).toBe("http://localhost:8001");
  });

  it("defaults requireMention to true when unspecified", () => {
    const cfg = readChannelConfig({
      channels: {
        "mycelium-room": {
          backendUrl: "http://localhost:8001",
          room: "r",
          agents: ["a"],
        },
      },
    });
    expect(cfg?.requireMention).toBe(true);
  });

  it("respects explicit requireMention=false", () => {
    const cfg = readChannelConfig({
      channels: {
        "mycelium-room": {
          backendUrl: "http://localhost:8001",
          room: "r",
          agents: ["a"],
          requireMention: false,
        },
      },
    });
    expect(cfg?.requireMention).toBe(false);
  });

  it("treats any non-false requireMention value as true (guards against typos)", () => {
    // Only exactly `false` disables it — strings, null, undefined all enable
    const cfg = readChannelConfig({
      channels: {
        "mycelium-room": {
          backendUrl: "http://localhost:8001",
          room: "r",
          agents: ["a"],
          requireMention: null,
        },
      },
    });
    expect(cfg?.requireMention).toBe(true);
  });

  it("uses the legacy handle field when agents array is missing", () => {
    const cfg = readChannelConfig({
      channels: {
        "mycelium-room": {
          backendUrl: "http://localhost:8001",
          room: "r",
          handle: "main",
        },
      },
    });
    expect(cfg?.agents).toEqual(["main"]);
  });

  it("prefers agents[] over handle when both are present", () => {
    const cfg = readChannelConfig({
      channels: {
        "mycelium-room": {
          backendUrl: "http://localhost:8001",
          room: "r",
          agents: ["julia", "selina"],
          handle: "legacy",
        },
      },
    });
    expect(cfg?.agents).toEqual(["julia", "selina"]);
  });

  it("defaults to ['main'] when neither agents nor handle is present", () => {
    const cfg = readChannelConfig({
      channels: {
        "mycelium-room": {
          backendUrl: "http://localhost:8001",
          room: "r",
        },
      },
    });
    expect(cfg?.agents).toEqual(["main"]);
  });

  it("coerces non-string agent values to strings", () => {
    const cfg = readChannelConfig({
      channels: {
        "mycelium-room": {
          backendUrl: "http://localhost:8001",
          room: "r",
          agents: [123, "julia"],
        },
      },
    });
    expect(cfg?.agents).toEqual(["123", "julia"]);
  });

  it("falls back to default when agents is present but empty", () => {
    const cfg = readChannelConfig({
      channels: {
        "mycelium-room": {
          backendUrl: "http://localhost:8001",
          room: "r",
          agents: [],
        },
      },
    });
    // Empty array doesn't match the len > 0 guard, so we fall through to handle, then to default
    expect(cfg?.agents).toEqual(["main"]);
  });
});

describe("readChannelConfigs (multi-room fan-out)", () => {
  it("returns [] for null / empty / disabled / no backendUrl", () => {
    expect(readChannelConfigs(null)).toEqual([]);
    expect(readChannelConfigs({})).toEqual([]);
    expect(readChannelConfigs({ channels: { discord: {} } })).toEqual([]);
    expect(
      readChannelConfigs({
        channels: { "mycelium-room": { room: "r" } },
      }),
    ).toEqual([]);
    expect(
      readChannelConfigs({
        channels: {
          "mycelium-room": {
            enabled: false,
            backendUrl: "http://localhost:8000",
            room: "r",
          },
        },
      }),
    ).toEqual([]);
  });

  it("legacy single-room block → exactly one config", () => {
    const cfgs = readChannelConfigs({
      channels: {
        "mycelium-room": {
          backendUrl: "http://localhost:8000",
          room: "alpha",
          agents: ["a", "b"],
        },
      },
    });
    expect(cfgs).toEqual([
      {
        backendUrl: "http://localhost:8000",
        room: "alpha",
        agents: ["a", "b"],
        requireMention: true,
      },
    ]);
  });

  it("rooms[] fan-out → one config per room, shared backendUrl/requireMention", () => {
    const cfgs = readChannelConfigs({
      channels: {
        "mycelium-room": {
          backendUrl: "http://localhost:8000/",
          requireMention: false,
          rooms: [
            { room: "alpha", agents: ["a"] },
            { room: "beta", agents: ["b", "c"] },
          ],
        },
      },
    });
    expect(cfgs).toEqual([
      {
        backendUrl: "http://localhost:8000",
        room: "alpha",
        agents: ["a"],
        requireMention: false,
      },
      {
        backendUrl: "http://localhost:8000",
        room: "beta",
        agents: ["b", "c"],
        requireMention: false,
      },
    ]);
  });

  it("mixed: top-level room PLUS rooms[] — all of them, top-level first", () => {
    const cfgs = readChannelConfigs({
      channels: {
        "mycelium-room": {
          backendUrl: "http://localhost:8000",
          room: "alpha",
          agents: ["a"],
          rooms: [{ room: "beta", agents: ["b"] }],
        },
      },
    });
    expect(cfgs.map((c) => c.room)).toEqual(["alpha", "beta"]);
    expect(cfgs[1].agents).toEqual(["b"]);
  });

  it("de-dupes a room that appears both top-level and in rooms[]", () => {
    const cfgs = readChannelConfigs({
      channels: {
        "mycelium-room": {
          backendUrl: "http://localhost:8000",
          room: "alpha",
          agents: ["a"],
          rooms: [{ room: "alpha", agents: ["dupe"] }, { room: "beta", agents: ["b"] }],
        },
      },
    });
    // alpha keeps the top-level definition; the rooms[] dupe is dropped.
    expect(cfgs.map((c) => c.room)).toEqual(["alpha", "beta"]);
    expect(cfgs[0].agents).toEqual(["a"]);
  });

  it("skips rooms[] entries without a room name", () => {
    const cfgs = readChannelConfigs({
      channels: {
        "mycelium-room": {
          backendUrl: "http://localhost:8000",
          rooms: [{ agents: ["x"] }, { room: "beta", agents: ["b"] }],
        },
      },
    });
    expect(cfgs.map((c) => c.room)).toEqual(["beta"]);
  });

  it("readChannelConfig shim returns the first config (legacy callers)", () => {
    const cfg = readChannelConfig({
      channels: {
        "mycelium-room": {
          backendUrl: "http://localhost:8000",
          rooms: [
            { room: "alpha", agents: ["a"] },
            { room: "beta", agents: ["b"] },
          ],
        },
      },
    });
    expect(cfg?.room).toBe("alpha");
  });
});
