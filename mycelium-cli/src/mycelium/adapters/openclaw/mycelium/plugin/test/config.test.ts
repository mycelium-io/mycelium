// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Cisco Systems, Inc. and its affiliates

import { describe, expect, it } from "vitest";
import { readChannelConfig } from "../src/config.js";

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
