// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/room-data", () => ({
  useRoomUploads: () => ({
    uploads: [
      {
        key: "uploads/shot.png",
        filename: "shot.png",
        kind: "image",
        size: 2048,
        url: "/api/rooms/demo/uploads/shot.png/raw",
        created_by: "operator",
        created_at: "2026-10-09T10:00:00Z",
      },
    ],
    loading: false,
  }),
}));

import { MessageBody } from "@/components/message-body";

describe("<MessageBody />", () => {
  const scrollHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollHeight");

  beforeEach(() => {
    // Every element measures tall, so the prose clamps.
    Object.defineProperty(HTMLElement.prototype, "scrollHeight", { configurable: true, get: () => 1000 });
  });
  afterEach(() => {
    if (scrollHeight) Object.defineProperty(HTMLElement.prototype, "scrollHeight", scrollHeight);
  });

  it("puts Show more with the prose it opens, above the message's files", () => {
    render(<MessageBody roomName="demo" content={"A long note.\n\n[[uploads/shot.png]]"} />);

    const toggle = screen.getByRole("button", { name: /show more/i });
    const file = screen.getByRole("button", { name: "Preview shot.png" });
    expect(toggle.compareDocumentPosition(file) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});
