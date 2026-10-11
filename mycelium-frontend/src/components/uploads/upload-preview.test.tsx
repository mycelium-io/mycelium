// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// The preview steps through the files it was opened among, a message's
// attachments, with its arrows or the arrow keys, wrapping at the ends.

import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { stepThrough, UploadPreviewDialog } from "@/components/uploads/upload-preview";
import type { Upload } from "@/lib/api";

function image(n: number): Upload {
  return {
    name: `shot-${n}.png`,
    key: `uploads/shot-${n}.png`,
    filename: `shot-${n}.png`,
    kind: "image",
    content_type: "image/png",
    size: 1024,
    sha256: `h${n}`,
    created_by: "julia",
    created_at: "2026-10-09T12:00:00Z",
    url: `/api/rooms/r/uploads/shot-${n}.png`,
  };
}

const SET = [image(1), image(2), image(3)];

describe("stepThrough", () => {
  it("steps forward and back, wrapping at the ends", () => {
    expect(stepThrough(SET, SET[0], 1)?.key).toBe(SET[1].key);
    expect(stepThrough(SET, SET[2], 1)?.key).toBe(SET[0].key);
    expect(stepThrough(SET, SET[0], -1)?.key).toBe(SET[2].key);
  });

  it("has nowhere to go with one file, or one not in the set", () => {
    expect(stepThrough([SET[0]], SET[0], 1)).toBeNull();
    expect(stepThrough(SET, image(9), 1)).toBeNull();
    expect(stepThrough(SET, null, 1)).toBeNull();
  });
});

function Opened({ set, first }: { set: Upload[]; first: Upload }) {
  const [shown, setShown] = useState<Upload | null>(first);
  return <UploadPreviewDialog upload={shown} onClose={() => setShown(null)} set={set} onShow={setShown} />;
}

describe("<UploadPreviewDialog /> in a set", () => {
  it("says where it is and steps with its arrows", async () => {
    const user = userEvent.setup();
    render(<Opened set={SET} first={SET[0]} />);
    expect(screen.getByText("1 of 3")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Next file" }));
    expect(screen.getByText("2 of 3")).toBeInTheDocument();
    expect(screen.getByRole("img")).toHaveAttribute("alt", "shot-2.png");

    await user.click(screen.getByRole("button", { name: "Previous file" }));
    await user.click(screen.getByRole("button", { name: "Previous file" }));
    expect(screen.getByText("3 of 3")).toBeInTheDocument();
  });

  it("steps with the arrow keys", () => {
    render(<Opened set={SET} first={SET[1]} />);
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "ArrowRight" });
    expect(screen.getByText("3 of 3")).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "ArrowLeft" });
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "ArrowLeft" });
    expect(screen.getByText("1 of 3")).toBeInTheDocument();
  });

  it("shows the whole set as a strip, the shown one marked, and jumps to one clicked", async () => {
    const user = userEvent.setup();
    render(<Opened set={SET} first={SET[0]} />);
    expect(screen.getByRole("button", { name: "Show shot-1.png" })).toHaveAttribute("aria-current", "true");

    await user.click(screen.getByRole("button", { name: "Show shot-3.png" }));
    expect(screen.getByText("3 of 3")).toBeInTheDocument();
    expect(screen.getByRole("img")).toHaveAttribute("alt", "shot-3.png");
    expect(screen.getByRole("button", { name: "Show shot-3.png" })).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("button", { name: "Show shot-1.png" })).not.toHaveAttribute("aria-current");
  });

  it("still steps from a file that isn't an image", () => {
    const notes: Upload = { ...image(4), kind: "audio", filename: "notes.mp3", key: "uploads/notes.mp3" };
    render(<Opened set={[notes, SET[0]]} first={notes} />);
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "ArrowRight" });
    expect(screen.getByText("2 of 2")).toBeInTheDocument();
  });

  it("shows no arrows or strip for a single file", () => {
    render(<Opened set={[SET[0]]} first={SET[0]} />);
    expect(screen.queryByRole("button", { name: "Next file" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Show shot-1.png" })).toBeNull();
    expect(screen.queryByText(/of 1/)).toBeNull();
  });
});

describe("<UploadPreviewDialog /> zooming an image", () => {
  // jsdom lays nothing out: the image is fitted to 500x400 and is 1000px wide
  // itself, so 100% is twice the fitted size.
  const sizes: [string, number | boolean][] = [
    ["clientWidth", 500],
    ["clientHeight", 400],
    ["naturalWidth", 1000],
    ["complete", true],
  ];
  beforeEach(() => {
    for (const [name, value] of sizes) {
      Object.defineProperty(HTMLImageElement.prototype, name, { configurable: true, get: () => value });
    }
  });
  afterEach(() => {
    for (const [name] of sizes) delete (HTMLImageElement.prototype as unknown as Record<string, unknown>)[name];
  });

  const level = () => screen.getByRole("group", { name: "Zoom" }).querySelector("button:not([aria-label^='Zoom'])")!;
  const transform = () => (screen.getByRole("img") as HTMLImageElement).style.transform;
  const key = (k: string) => fireEvent.keyDown(screen.getByRole("dialog"), { key: k });

  it("zooms in and out with the keys and the buttons, and 0 goes back to fit", async () => {
    const user = userEvent.setup();
    render(<Opened set={SET} first={SET[0]} />);
    expect(level()).toHaveTextContent("Fit");
    expect(screen.getByRole("button", { name: "Zoom out" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(level()).toHaveTextContent("63%");
    key("+");
    expect(level()).toHaveTextContent("78%");
    key("-");
    expect(level()).toHaveTextContent("63%");
    await user.click(screen.getByRole("button", { name: "Zoom out" }));
    expect(level()).toHaveTextContent("Fit");

    key("=");
    key("0");
    expect(level()).toHaveTextContent("Fit");
    expect(transform()).toBe("");
  });

  it("toggles between fit and 100% with a double-click", () => {
    render(<Opened set={SET} first={SET[0]} />);
    fireEvent.doubleClick(screen.getByTestId("zoom-frame"), { clientX: 0, clientY: 0 });
    expect(level()).toHaveTextContent("100%");
    fireEvent.doubleClick(screen.getByTestId("zoom-frame"), { clientX: 0, clientY: 0 });
    expect(level()).toHaveTextContent("Fit");
  });

  it("pans with a drag only when zoomed in", () => {
    render(<Opened set={SET} first={SET[0]} />);
    const frame = screen.getByTestId("zoom-frame");
    const dragBy = (dx: number) => {
      fireEvent.pointerDown(frame, { pointerId: 1, button: 0, clientX: 300, clientY: 200 });
      fireEvent.pointerMove(frame, { pointerId: 1, clientX: 300 + dx, clientY: 200 });
      fireEvent.pointerUp(frame, { pointerId: 1 });
    };
    dragBy(-50);
    expect(transform()).toBe("");

    fireEvent.doubleClick(frame, { clientX: 0, clientY: 0 });
    expect(transform()).toBe("translate(0px, 0px) scale(2)");
    dragBy(-50);
    expect(transform()).toBe("translate(-50px, 0px) scale(2)");
  });

  it("steps with the arrows at fit, and pans with them when zoomed", () => {
    render(<Opened set={SET} first={SET[0]} />);
    key("ArrowRight");
    expect(screen.getByText("2 of 3")).toBeInTheDocument();

    fireEvent.doubleClick(screen.getByTestId("zoom-frame"), { clientX: 0, clientY: 0 });
    key("ArrowRight");
    expect(screen.getByText("2 of 3")).toBeInTheDocument();
    expect(transform()).toBe("translate(-50px, 0px) scale(2)");
    key("ArrowDown");
    expect(transform()).toBe("translate(-50px, -40px) scale(2)");
  });

  it("zooms with a pinch or a mouse wheel's notch, and pans with a two-finger scroll", () => {
    render(<Opened set={SET} first={SET[0]} />);
    const frame = screen.getByTestId("zoom-frame");
    // A trackpad scroll at fit is left to the window.
    fireEvent.wheel(frame, { deltaY: 53, clientX: 0, clientY: 0 });
    expect(level()).toHaveTextContent("Fit");
    fireEvent.wheel(frame, { deltaY: -100, clientX: 0, clientY: 0 });
    expect(level()).not.toHaveTextContent("Fit");
    fireEvent.wheel(frame, { deltaY: -30, ctrlKey: true, clientX: 0, clientY: 0 });
    const zoomed = transform();
    expect(zoomed).toMatch(/scale\(1\.(?!0)/);
    fireEvent.wheel(frame, { deltaX: 20, deltaY: 53, clientX: 0, clientY: 0 });
    expect(transform()).not.toBe(zoomed);
    expect(transform()).toMatch(/^translate\(-20px, -53px\)/);
  });

  it("opens each file at fit", async () => {
    const user = userEvent.setup();
    render(<Opened set={SET} first={SET[0]} />);
    key("+");
    expect(level()).not.toHaveTextContent("Fit");
    await user.click(screen.getByRole("button", { name: "Next file" }));
    expect(screen.getByText("2 of 3")).toBeInTheDocument();
    expect(level()).toHaveTextContent("Fit");
  });
});
