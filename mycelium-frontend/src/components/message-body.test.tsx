// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { fireEvent, render, screen } from "@testing-library/react";
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

  // The case that failed: an agent wrote its picture as an embed, `![[…]]`,
  // which drew no thumbnail, and its chip opened the upload's memory tab
  // instead of the preview.
  it("opens the preview for a picture written as an embed", async () => {
    render(<MessageBody roomName="demo" content={"Before (main):\n![[uploads/shot.png]]\n\nSay yes."} />);

    fireEvent.click(screen.getByRole("button", { name: "Preview shot.png" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("opens the preview, not the memory, from an embed's chip in the prose", async () => {
    const onOpenMemory = vi.fn();
    render(
      <MessageBody roomName="demo" onOpenMemory={onOpenMemory} content={"Before:\n![[uploads/shot.png]]\nAfter: soon."} />,
    );

    fireEvent.click(screen.getByRole("button", { name: /uploads\/shot\.png/ }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(onOpenMemory).not.toHaveBeenCalled();
  });
});
