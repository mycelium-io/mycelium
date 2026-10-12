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

  // A press as a browser sends it: down, any moves, up, then the click.
  const press = (el: HTMLElement, from: [number, number], to: [number, number] = from, detail = 1) => {
    fireEvent.pointerDown(el, { pointerId: 1, button: 0, clientX: from[0], clientY: from[1] });
    if (to !== from) fireEvent.pointerMove(el, { pointerId: 1, clientX: to[0], clientY: to[1] });
    fireEvent.pointerUp(el, { pointerId: 1, clientX: to[0], clientY: to[1] });
    fireEvent.click(el, { clientX: to[0], clientY: to[1], detail });
  };

  it("zooms in to 100% at the point clicked, and a click while zoomed goes back to fit", () => {
    render(<Opened set={SET} first={SET[0]} />);
    const frame = screen.getByTestId("zoom-frame");
    press(frame, [100, 50]);
    expect(level()).toHaveTextContent("100%");
    // The point clicked stays under the pointer: (100, 50) at twice the size.
    expect(transform()).toBe("translate(-100px, -50px) scale(2)");
    // A press that wanders a pixel or two is still a click.
    press(frame, [300, 200], [302, 201]);
    expect(level()).toHaveTextContent("Fit");
  });

  it("counts a double-click as one click", () => {
    render(<Opened set={SET} first={SET[0]} />);
    const frame = screen.getByTestId("zoom-frame");
    press(frame, [0, 0]);
    press(frame, [0, 0], [0, 0], 2);
    fireEvent.doubleClick(frame, { clientX: 0, clientY: 0 });
    expect(level()).toHaveTextContent("100%");
  });

  it("pans with a drag when zoomed in, without going back to fit", () => {
    render(<Opened set={SET} first={SET[0]} />);
    const frame = screen.getByTestId("zoom-frame");
    // At fit, a drag neither pans nor zooms.
    press(frame, [300, 200], [250, 200]);
    expect(transform()).toBe("");
    expect(level()).toHaveTextContent("Fit");

    press(frame, [0, 0]);
    expect(transform()).toBe("translate(0px, 0px) scale(2)");
    press(frame, [300, 200], [250, 200]);
    expect(transform()).toBe("translate(-50px, 0px) scale(2)");
    expect(level()).toHaveTextContent("100%");
  });

  it("shows a minimap only when zoomed in, framing the part in view, and pans when it's dragged", () => {
    render(<Opened set={SET} first={SET[0]} />);
    expect(screen.queryByTestId("minimap")).toBeNull();

    press(screen.getByTestId("zoom-frame"), [0, 0]);
    const map = screen.getByTestId("minimap");
    // 150px wide (30% of the 500px box), so a scale of 0.3; at 2x the view is
    // the top-left quarter of the image.
    expect(map.style.width).toBe("150px");
    const rect = screen.getByTestId("minimap-view");
    expect([rect.style.left, rect.style.top, rect.style.width, rect.style.height]).toEqual(["0px", "0px", "75px", "60px"]);

    // Grab the rectangle at its middle and drag it to the map's middle.
    fireEvent.pointerDown(map, { pointerId: 2, button: 0, clientX: 37.5, clientY: 30 });
    expect(transform()).toBe("translate(0px, 0px) scale(2)");
    fireEvent.pointerMove(map, { pointerId: 2, clientX: 75, clientY: 60 });
    fireEvent.pointerUp(map, { pointerId: 2 });
    fireEvent.click(map);
    expect(transform()).toBe("translate(-250px, -200px) scale(2)");
    expect([rect.style.left, rect.style.top]).toEqual(["37.5px", "30px"]);
    // Pressing the map isn't a click on the image: it's still zoomed in.
    expect(level()).toHaveTextContent("100%");

    // Clicking elsewhere on it centers the view there, as far as the edges allow.
    fireEvent.pointerDown(map, { pointerId: 3, button: 0, clientX: 0, clientY: 0 });
    expect(transform()).toBe("translate(0px, 0px) scale(2)");
  });

  it("steps with the arrows at fit, and pans with them when zoomed", () => {
    render(<Opened set={SET} first={SET[0]} />);
    key("ArrowRight");
    expect(screen.getByText("2 of 3")).toBeInTheDocument();

    press(screen.getByTestId("zoom-frame"), [0, 0]);
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
