// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// The Files tab: a room's uploads as a gallery, opened in the preview window,
// filtered, linked back to their messages, and deleted only after asking.

import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Upload } from "@/lib/api";

const THREAD = "urn:ioc:mycelium:episode:r:t1";
// Hours before noon today, local time, so "today" holds whatever the clock says.
const noon = new Date();
noon.setHours(12, 0, 0, 0);
const at = (hoursAgo: number) => new Date(noon.getTime() - hoursAgo * 3_600_000).toISOString();

function file(name: string, hoursAgo: number, extra: Partial<Upload> = {}): Upload {
  return {
    name,
    key: `uploads/${name}`,
    filename: name,
    kind: name.endsWith(".png") ? "image" : "pdf",
    content_type: "",
    size: 2048,
    sha256: name,
    created_by: "julia",
    created_at: at(hoursAgo),
    url: `/api/rooms/r/uploads/${name}/raw`,
    thumb_url: name.endsWith(".png") ? `/api/rooms/r/uploads/${name}/thumb?v=1` : null,
    ...extra,
  };
}

let FILES: Upload[] = [];
const refresh = vi.fn();
const deleteUpload = vi.fn<(room: string, name: string) => Promise<void>>(async () => {});

vi.mock("@/lib/room-data", () => ({
  useRoomUploads: () => ({ uploads: FILES, loading: false, refresh, accepted: [], max_bytes: 0, total: FILES.length }),
}));
vi.mock("@/lib/api", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/api")>()),
  deleteUpload: (room: string, name: string) => deleteUpload(room, name),
}));
vi.mock("@/components/uploads/pdf-preview", () => ({ PdfPreview: () => <div>pdf</div> }));

import { RoomFiles } from "@/components/files/room-files";

function renderFiles() {
  const handlers = { onOpenThread: vi.fn(), onOpenMessage: vi.fn(), onOpenMemory: vi.fn() };
  render(<RoomFiles roomName="r" {...handlers} />);
  return handlers;
}

const cards = () => screen.getAllByRole("button", { name: /^Preview / }).map((b) => b.getAttribute("aria-label"));

beforeEach(() => {
  refresh.mockClear();
  deleteUpload.mockClear();
  FILES = [
    file("spec.pdf", 50, { posted_in: { message_id: "m2", sender: "builder", at: at(50), episode: THREAD, task: "work/settings", task_title: "Fix settings" } }),
    file("shot-1.png", 2, { posted_in: { message_id: "m1", sender: "julia", at: at(2), episode: null } }),
    file("shot-2.png", 1, { posted_in: { message_id: "m3", sender: "julia", at: at(1), episode: THREAD, task: "work/settings", task_title: "Fix settings" } }),
    file("notes.pdf", 1.5),
  ];
});

describe("<RoomFiles />", () => {
  it("lists files newest first, grouped by day, with small thumbnails", () => {
    renderFiles();
    expect(cards()).toEqual(["Preview shot-2.png", "Preview notes.pdf", "Preview shot-1.png", "Preview spec.pdf"]);
    const todayGroup = screen.getByRole("region", { name: "Today" });
    expect(within(todayGroup).getAllByRole("button", { name: /^Preview / })).toHaveLength(3);
    // The grid loads the hub's thumbnail, never the full image.
    const thumb = within(todayGroup).getByRole("button", { name: "Preview shot-2.png" }).querySelector("img");
    expect(thumb).toHaveAttribute("src", "/api/rooms/r/uploads/shot-2.png/thumb?v=1");
  });

  it("narrows with the filters, and says when nothing is left", async () => {
    const user = userEvent.setup();
    renderFiles();
    await user.selectOptions(screen.getByRole("combobox", { name: "Kind of file" }), "images");
    expect(cards()).toEqual(["Preview shot-2.png", "Preview shot-1.png"]);
    await user.selectOptions(screen.getByRole("combobox", { name: "Posted in" }), "task:work/settings");
    expect(cards()).toEqual(["Preview shot-2.png"]);
    expect(screen.getByText("1 of 4")).toBeInTheDocument();
    await user.type(screen.getByRole("searchbox", { name: "Search file names" }), "nothing");
    expect(screen.getByText("No files match these filters.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear the filters" }));
    expect(cards()).toHaveLength(4);
  });

  it("opens the preview at the file clicked, and its arrows step through the gallery", async () => {
    const user = userEvent.setup();
    renderFiles();
    await user.click(screen.getByRole("button", { name: "Preview notes.pdf" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("2 of 4")).toBeInTheDocument();
    fireEvent.keyDown(dialog, { key: "ArrowRight" });
    expect(within(dialog).getByText("3 of 4")).toBeInTheDocument();
    expect(within(dialog).getByRole("heading", { name: "shot-1.png" })).toBeInTheDocument();
    fireEvent.keyDown(dialog, { key: "ArrowRight" });
    fireEvent.keyDown(dialog, { key: "ArrowRight" });
    expect(within(dialog).getByRole("heading", { name: "shot-2.png" })).toBeInTheDocument();
  });

  it("links each file to the message it was posted with", async () => {
    const user = userEvent.setup();
    const handlers = renderFiles();
    const card = (name: string) => screen.getByRole("button", { name: `Preview ${name}` }).closest("li")!;
    await user.click(within(card("shot-1.png")).getByRole("button", { name: "In the channel" }));
    expect(handlers.onOpenMessage).toHaveBeenCalledWith("m1");
    await user.click(within(card("shot-2.png")).getByRole("button", { name: "In Fix settings" }));
    expect(handlers.onOpenThread).toHaveBeenCalledWith(THREAD);
    await user.click(within(card("notes.pdf")).getByRole("button", { name: "Saved to memory" }));
    expect(handlers.onOpenMemory).toHaveBeenCalledWith("uploads/notes.pdf");
  });

  it("deletes the selected files only after asking, naming how many", async () => {
    const user = userEvent.setup();
    renderFiles();
    await user.click(screen.getByRole("checkbox", { name: "Select shot-1.png" }));
    await user.click(screen.getByRole("checkbox", { name: "Select spec.pdf" }));
    expect(screen.getByText("2 selected")).toBeInTheDocument();

    await user.click(within(screen.getByRole("toolbar", { name: "Selected files" })).getByRole("button", { name: /Delete/ }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("Delete 2 files?")).toBeInTheDocument();
    expect(deleteUpload).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", { name: "Delete 2 files" }));
    expect(deleteUpload.mock.calls.map((c) => c[1]).sort()).toEqual(["shot-1.png", "spec.pdf"]);
    expect(refresh).toHaveBeenCalled();
    expect(screen.queryByText("2 selected")).toBeNull();
  });

  it("says how to add a file when the room has none", () => {
    FILES = [];
    renderFiles();
    expect(screen.getByText("No files in this room yet")).toBeInTheDocument();
    expect(screen.getByText(/mycelium file upload/)).toBeInTheDocument();
  });
});
