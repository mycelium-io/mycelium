// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

import { describe, expect, it } from "vitest";

import { extractMyceliumRoomFromText } from "../src/session/index.js";

describe("extractMyceliumRoomFromText", () => {
  it("extracts --room <name> from CLI-style instructions", () => {
    const text =
      "Run: mycelium session join --handle alpha --room dist-e2e-abc123 -m 'hi'";
    expect(extractMyceliumRoomFromText(text)).toBe("dist-e2e-abc123");
  });

  it("extracts --room=<name> form", () => {
    expect(extractMyceliumRoomFromText("--room=mycelium_room")).toBe(
      "mycelium_room",
    );
  });

  it("extracts narrative 'Room: <name>' form", () => {
    const text = "Please coordinate.\nRoom: dist-e2e-xyz\nDeadline: 30s";
    expect(extractMyceliumRoomFromText(text)).toBe("dist-e2e-xyz");
  });

  it("extracts 'Mycelium Room: <name>' form", () => {
    const text = "Heads up — Mycelium Room: shared-roadmap";
    expect(extractMyceliumRoomFromText(text)).toBe("shared-roadmap");
  });

  it("preserves colons (session sub-room names)", () => {
    expect(
      extractMyceliumRoomFromText("--room dist-e2e-abc:session:42"),
    ).toBe("dist-e2e-abc:session:42");
  });

  it("returns null when no room mention present", () => {
    expect(extractMyceliumRoomFromText("hello world")).toBeNull();
    expect(extractMyceliumRoomFromText("")).toBeNull();
  });

  it("--room flag takes priority over narrative form", () => {
    const text = "Room: legacy-room\nmycelium session join --room new-room";
    expect(extractMyceliumRoomFromText(text)).toBe("new-room");
  });

  it("rejects characters outside the allowed set", () => {
    // Stops at the first disallowed char (space, slash, etc.)
    expect(extractMyceliumRoomFromText("--room foo/bar")).toBe("foo");
  });
});
