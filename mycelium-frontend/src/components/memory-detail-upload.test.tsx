// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// An image upload's own memory tab opens the lightbox on a click, as the same
// image does in a message. It used to sit there, static.

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({
  fetchMemoryLinks: vi.fn().mockResolvedValue({ key: "uploads/shot.png", outbound: [], backlinks: [] }),
}));
vi.mock("@/lib/room-data", () => ({
  useRoomUploads: () => ({
    uploads: [
      {
        key: "uploads/shot.png",
        filename: "shot.png",
        kind: "image",
        size: 2048,
        url: "/api/rooms/demo/uploads/shot.png/raw",
        created_by: "desktop",
        created_at: "2026-10-21T00:17:00Z",
      },
    ],
    loading: false,
  }),
}));

import { MemoryDetail, type MemoryLike } from "@/components/memory-detail";

const memory: MemoryLike = {
  key: "uploads/shot.png",
  value: { text: "An image, 2 KB." },
  content_text: "An image, 2 KB.",
  version: 1,
  created_by: "desktop",
};

describe("an image upload's memory", () => {
  it("opens the lightbox when its picture is clicked", async () => {
    render(<MemoryDetail memory={memory} roomName="demo" variant="page" onNavigate={() => {}} />);

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Preview shot.png" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });
});
