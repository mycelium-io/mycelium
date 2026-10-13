// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// Right-click an image to copy it, copy its link or download it, in the
// preview window and the Files tab; ⌘C copies it in the preview.

import { useState } from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { UploadPreviewDialog } from "@/components/uploads/upload-preview";
import type { Upload } from "@/lib/api";
import { copyImage, toPng } from "@/lib/clipboard";

vi.mock("@/components/uploads/pdf-preview", () => ({ PdfPreview: () => <div>pdf</div> }));

function file(name: string, kind: Upload["kind"] = "image"): Upload {
  return {
    name,
    key: `uploads/${name}`,
    filename: name,
    kind,
    content_type: kind === "image" ? "image/png" : "audio/mpeg",
    size: 1024,
    sha256: name,
    created_by: "julia",
    created_at: "2026-10-13T12:00:00Z",
    url: `/api/rooms/r/uploads/${name}/raw`,
  };
}

// The clipboard as a browser gives it: `write` takes items, each holding a
// promise of its data. jsdom has neither, so they stand in here.
class FakeClipboardItem {
  constructor(readonly items: Record<string, Promise<Blob> | Blob>) {}
}
const written: FakeClipboardItem[][] = [];
const clipboard = {
  write: vi.fn(async (items: FakeClipboardItem[]) => {
    for (const item of items) for (const v of Object.values(item.items)) await v;
    written.push(items);
  }),
  writeText: vi.fn<(text: string) => Promise<void>>(async () => {}),
};
const png = new Blob(["png"], { type: "image/png" });

beforeEach(() => {
  written.length = 0;
  clipboard.write.mockClear();
  clipboard.writeText.mockClear();
  vi.stubGlobal("ClipboardItem", FakeClipboardItem);
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: clipboard });
  vi.stubGlobal("fetch", vi.fn(async () => new Response(png, { headers: { "Content-Type": "image/png" } })));
});
afterEach(() => {
  vi.unstubAllGlobals();
  window.getSelection()?.removeAllRanges();
});

describe("copyImage", () => {
  it("puts the image on the clipboard as a PNG", async () => {
    await copyImage("/api/rooms/r/uploads/a.png/raw");
    const [[item]] = written;
    expect(Object.keys(item.items)).toEqual(["image/png"]);
    expect((await item.items["image/png"]).type).toBe("image/png");
  });

  it("says why when the browser can't copy images, or the file won't load", async () => {
    vi.stubGlobal("ClipboardItem", undefined);
    await expect(copyImage("/x")).rejects.toThrow("can't copy images");
    vi.stubGlobal("ClipboardItem", FakeClipboardItem);
    vi.stubGlobal("fetch", vi.fn(async () => new Response("gone", { status: 404 })));
    await expect(copyImage("/x")).rejects.toThrow("couldn't be loaded");
  });
});

describe("toPng", () => {
  it("keeps a PNG, and redraws anything else on a canvas as one", async () => {
    expect(await toPng(png)).toBe(png);
    const bitmap = { width: 4, height: 3, close: vi.fn() };
    vi.stubGlobal("createImageBitmap", vi.fn(async () => bitmap));
    const drawImage = vi.fn();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({ drawImage } as unknown as CanvasRenderingContext2D);
    vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation(function (this: HTMLCanvasElement, done, type) {
      expect([this.width, this.height, type]).toEqual([4, 3, "image/png"]);
      done(png);
    });
    const jpeg = new Blob(["jpg"], { type: "image/jpeg" });
    expect(await toPng(jpeg)).toBe(png);
    expect(drawImage).toHaveBeenCalledWith(bitmap, 0, 0);
    expect(bitmap.close).toHaveBeenCalled();
  });
});

function Opened({ set }: { set: Upload[] }) {
  const [shown, setShown] = useState<Upload | null>(set[0]);
  return <UploadPreviewDialog upload={shown} onClose={() => setShown(null)} set={set} onShow={setShown} />;
}

const menuOn = async (el: HTMLElement) => {
  fireEvent.contextMenu(el, { clientX: 20, clientY: 20 });
  return await screen.findByRole("menu");
};

describe("the preview's right-click menu", () => {
  it("offers Copy image, Copy link and Download on an image", async () => {
    render(<Opened set={[file("shot.png")]} />);
    const menu = await menuOn(screen.getByTestId("zoom-frame"));
    expect(within(menu).getAllByRole("menuitem").map((m) => m.textContent?.replace(/⌘C|Ctrl\+C/, "").trim())).toEqual([
      "Copy image",
      "Copy link",
      "Download",
    ]);
  });

  it("copies the image, and says so", async () => {
    render(<Opened set={[file("shot.png")]} />);
    fireEvent.click(within(await menuOn(screen.getByTestId("zoom-frame"))).getByText("Copy image"));
    await waitFor(() => expect(clipboard.write).toHaveBeenCalledOnce());
    expect(await screen.findByText("Image copied")).toBeInTheDocument();
  });

  it("copies the file's full link, and says so", async () => {
    render(<Opened set={[file("shot.png")]} />);
    fireEvent.click(within(await menuOn(screen.getByTestId("zoom-frame"))).getByText("Copy link"));
    await waitFor(() =>
      expect(clipboard.writeText).toHaveBeenCalledWith(`${window.location.origin}/api/rooms/r/uploads/shot.png/raw`),
    );
    expect(await screen.findByText("Link copied")).toBeInTheDocument();
  });

  it("downloads the file", async () => {
    const clicked = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      expect([this.getAttribute("href"), this.download]).toEqual(["/api/rooms/r/uploads/shot.png/raw?download=1", "shot.png"]);
    });
    render(<Opened set={[file("shot.png")]} />);
    fireEvent.click(within(await menuOn(screen.getByTestId("zoom-frame"))).getByText("Download"));
    expect(clicked).toHaveBeenCalledOnce();
    clicked.mockRestore();
  });

  it("says plainly when copying fails", async () => {
    clipboard.write.mockRejectedValueOnce(Object.assign(new Error("denied"), { name: "NotAllowedError" }));
    render(<Opened set={[file("shot.png")]} />);
    fireEvent.click(within(await menuOn(screen.getByTestId("zoom-frame"))).getByText("Copy image"));
    expect(await screen.findByText("The browser didn't allow copying the image.")).toBeInTheDocument();
  });
});

describe("⌘C in the preview", () => {
  it("copies the image when nothing is selected", async () => {
    render(<Opened set={[file("shot.png")]} />);
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "c", metaKey: true });
    await waitFor(() => expect(clipboard.write).toHaveBeenCalledOnce());
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "c", ctrlKey: true });
    await waitFor(() => expect(clipboard.write).toHaveBeenCalledTimes(2));
  });

  it("leaves selected text to the browser's own copy", () => {
    render(<Opened set={[file("shot.png")]} />);
    const title = screen.getByRole("heading", { name: "shot.png" });
    const range = document.createRange();
    range.selectNodeContents(title);
    window.getSelection()?.addRange(range);
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "c", metaKey: true });
    expect(clipboard.write).not.toHaveBeenCalled();
  });

  it("does nothing on a file that isn't an image", () => {
    render(<Opened set={[file("notes.mp3", "audio")]} />);
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "c", metaKey: true });
    expect(clipboard.write).not.toHaveBeenCalled();
  });
});
