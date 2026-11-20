// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// An image attachment holds its space with a skeleton while it loads, settles
// to the image's shape once it does, and shows its name if it fails.

import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Upload } from "@/lib/api";

const roomUploads = vi.hoisted(() => ({
  uploads: [] as Upload[],
  loading: false,
  refresh: (async () => {}) as () => Promise<void>,
}));
vi.mock("@/lib/room-data", () => ({ useRoomUploads: () => roomUploads }));

import { AttachmentStrip } from "@/components/uploads/attachment-strip";

const SHOT: Upload = {
  name: "shot.png",
  key: "uploads/shot.png",
  filename: "shot.png",
  kind: "image",
  content_type: "image/png",
  size: 1024,
  sha256: "h1",
  created_by: "julia",
  created_at: "2026-10-09T12:00:00Z",
  url: "/api/rooms/r/uploads/shot.png",
};

function strip() {
  return render(<AttachmentStrip roomName="r" keys={[SHOT.key]} onOpen={() => {}} />);
}

describe("AttachmentStrip", () => {
  it("holds an image's space with a skeleton before the room's files arrive", () => {
    roomUploads.uploads = [];
    roomUploads.loading = true;
    const { container } = strip();
    const skeleton = container.querySelector(".animate-pulse");
    expect(skeleton).not.toBeNull();
    expect(skeleton?.className).toContain("h-32");
  });

  it("shows a skeleton in a fixed-height frame until the image loads, then sizes to it", () => {
    roomUploads.uploads = [SHOT];
    roomUploads.loading = false;
    const { container } = strip();
    const frame = screen.getByRole("button", { name: "Preview shot.png" });
    expect(frame.style.height).toBe("128px");
    expect(container.querySelector(".animate-pulse")).not.toBeNull();

    const img = screen.getByAltText("shot.png") as HTMLImageElement;
    Object.defineProperty(img, "naturalWidth", { value: 400 });
    Object.defineProperty(img, "naturalHeight", { value: 200 });
    fireEvent.load(img);

    expect(container.querySelector(".animate-pulse")).toBeNull();
    expect(frame.style.width).toBe("256px");
    expect(frame.style.height).toBe("128px");
  });

  it("doesn't call a file removed when the room's list was read before it was added", async () => {
    roomUploads.uploads = [];
    roomUploads.loading = false;
    let answer = () => {};
    roomUploads.refresh = vi.fn(() => new Promise<void>((done) => (answer = done)));
    const { container, rerender } = strip();
    // The list it has doesn't know the file yet: a placeholder, and the list is fetched again.
    expect(screen.queryByText(/was removed/)).toBeNull();
    expect(container.querySelector(".animate-pulse")).not.toBeNull();
    expect(roomUploads.refresh).toHaveBeenCalledTimes(1);

    // The new list has it.
    roomUploads.uploads = [SHOT];
    await act(async () => answer());
    rerender(<AttachmentStrip roomName="r" keys={[SHOT.key]} onOpen={() => {}} />);
    expect(screen.queryByText(/was removed/)).toBeNull();
    expect(screen.getByAltText("shot.png")).toBeTruthy();
  });

  it("calls a file removed once a fresh read of the room's list still doesn't have it", async () => {
    roomUploads.uploads = [];
    roomUploads.loading = false;
    roomUploads.refresh = vi.fn(async () => {});
    strip();
    expect(await screen.findByText("shot.png was removed")).toBeTruthy();
    expect(roomUploads.refresh).toHaveBeenCalledTimes(1);
  });

  it("shows the file's name when the image fails to load", () => {
    roomUploads.uploads = [SHOT];
    roomUploads.loading = false;
    strip();
    fireEvent.error(screen.getByAltText("shot.png"));
    expect(screen.getByText("shot.png")).toBeTruthy();
    expect(screen.getByText("Couldn't load the image")).toBeTruthy();
  });
});
