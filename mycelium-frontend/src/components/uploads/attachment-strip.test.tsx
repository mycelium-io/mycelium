// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// An image attachment holds its space with a skeleton while it loads, settles
// to the image's shape once it does, and shows its name if it fails.

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Upload } from "@/lib/api";

const roomUploads = vi.hoisted(() => ({ uploads: [] as Upload[], loading: false }));
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

  it("shows the file's name when the image fails to load", () => {
    roomUploads.uploads = [SHOT];
    roomUploads.loading = false;
    strip();
    fireEvent.error(screen.getByAltText("shot.png"));
    expect(screen.getByText("shot.png")).toBeTruthy();
    expect(screen.getByText("Couldn't load the image")).toBeTruthy();
  });
});

describe("Download all", () => {
  const NOTES: Upload = {
    ...SHOT,
    name: "notes.md",
    key: "uploads/notes.md",
    filename: "notes.md",
    kind: "text",
    content_type: "text/plain",
    url: "/api/rooms/r/uploads/notes.md",
  };
  const SHOT2: Upload = { ...SHOT, name: "shot-2.png", key: "uploads/shot-2.png", url: "/api/rooms/r/uploads/shot-2.png" };

  it("isn't offered for a message with one file", () => {
    roomUploads.uploads = [SHOT];
    roomUploads.loading = false;
    strip();
    expect(screen.queryByRole("button", { name: /Download all/ })).toBeNull();
  });

  it("saves every file as one zip named after the room, two files of one name kept apart", async () => {
    roomUploads.uploads = [SHOT, NOTES, SHOT2];
    roomUploads.loading = false;
    const fetched: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        fetched.push(url);
        return new Response(new TextEncoder().encode(url));
      }),
    );
    const saved: { name: string; size: number }[] = [];
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      saved.push({ name: this.download, size: 0 });
    });
    URL.createObjectURL = vi.fn(() => "blob:zip");
    URL.revokeObjectURL = vi.fn();

    render(<AttachmentStrip roomName="checkout" keys={[SHOT.key, NOTES.key, SHOT2.key]} onOpen={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: /Download all/ }));

    await vi.waitFor(() => expect(saved).toHaveLength(1));
    expect(fetched).toEqual([SHOT.url, NOTES.url, SHOT2.url].map((u) => expect.stringContaining(`${u}?download=1`)));
    expect(saved[0].name).toMatch(/^checkout-\d{4}-\d{2}-\d{2}-\d{4}\.zip$/);
    click.mockRestore();
    vi.unstubAllGlobals();
  });
});
