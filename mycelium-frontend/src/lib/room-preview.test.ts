// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { latestPreview } from "@/lib/room-preview";
import type { RoomMessage } from "@/lib/api";

const chat = (sender: string, content: unknown, at = "2026-08-12T10:00:00Z"): RoomMessage => ({
  message_type: "broadcast",
  sender_handle: sender,
  content,
  created_at: at,
});

describe("latestPreview", () => {
  it("takes the newest chat line, transcript order being newest-first", () => {
    const preview = latestPreview([chat("risk", "hold the dual-write"), chat("growth", "ship it")]);
    expect(preview).toEqual({ sender: "risk", text: "hold the dual-write", at: "2026-08-12T10:00:00Z" });
  });

  it("returns null for a room with no messages", () => {
    expect(latestPreview([])).toBeNull();
  });

  it("collapses newlines so a multi-line post stays one row", () => {
    expect(latestPreview([chat("growth", "line one\n\n  line two ")])?.text).toBe("line one line two");
  });

  it("truncates a long post rather than letting it set the row width", () => {
    const text = latestPreview([chat("growth", "x".repeat(400))])?.text ?? "";
    expect(text.length).toBeLessThanOrEqual(180);
    expect(text.endsWith("…")).toBe(true);
  });

  it("unwraps a chat message that arrived as a {text: …} envelope", () => {
    expect(latestPreview([chat("aligner", JSON.stringify({ text: "round 2" }))])?.text).toBe("round 2");
  });

  it("prefers a chat line over the protocol events sitting on top of it", () => {
    const preview = latestPreview([
      { message_type: "coordination_tick", sender_handle: "aligner", content: "{}" },
      { message_type: "coordination_tick", sender_handle: "aligner", content: "{}" },
      chat("growth", "phased cutover works for me"),
    ]);
    expect(preview?.text).toBe("phased cutover works for me");
    expect(preview?.sender).toBe("growth");
  });

  it("names a room event when nobody has spoken in the scanned window", () => {
    const preview = latestPreview([
      { message_type: "coordination_start", sender_handle: "aligner", created_at: "2026-08-12T09:00:00Z" },
    ]);
    expect(preview).toEqual({ sender: "aligner", text: "negotiation opened", at: "2026-08-12T09:00:00Z" });
  });

  it("gives up rather than previewing a wall of protocol ticks", () => {
    const ticks = Array.from({ length: 20 }, () => ({
      message_type: "coordination_tick",
      sender_handle: "aligner",
      content: "{}",
    }));
    expect(latestPreview(ticks)).toBeNull();
  });

  it("skips a chat message whose content is not prose and keeps looking", () => {
    const preview = latestPreview([chat("aligner", { offer: 3 }), chat("risk", "still nervous")]);
    expect(preview?.text).toBe("still nervous");
  });
});
