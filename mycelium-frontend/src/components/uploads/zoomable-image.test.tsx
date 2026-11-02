// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// The full image always shows when it's opened: already loaded from the cache,
// loading late, decoding when first looked at, or failing, which says so with
// a way to try again instead of leaving the preview blank.

import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { ZoomableImage } from "@/components/uploads/zoomable-image";

// jsdom lays nothing out and decodes nothing, so the sizes are the test's.
let natural = { width: 0, height: 0, complete: false };
const restore: (() => void)[] = [];
function stub<T extends object>(proto: T, key: string, get: () => unknown) {
  const was = Object.getOwnPropertyDescriptor(proto, key);
  Object.defineProperty(proto, key, { configurable: true, get });
  restore.push(() => (was ? Object.defineProperty(proto, key, was) : delete (proto as Record<string, unknown>)[key]));
}

beforeEach(() => {
  natural = { width: 0, height: 0, complete: false };
  stub(HTMLElement.prototype, "clientWidth", () => 800);
  stub(HTMLElement.prototype, "clientHeight", () => 600);
  stub(HTMLImageElement.prototype, "naturalWidth", () => natural.width);
  stub(HTMLImageElement.prototype, "naturalHeight", () => natural.height);
  stub(HTMLImageElement.prototype, "complete", () => natural.complete);
});
afterEach(() => restore.splice(0).forEach((undo) => undo()));

const image = () => screen.getByRole("img", { name: "Checkout on a phone" });
const measured = () => image().style.width !== "";

describe("an opened image", () => {
  it("shows at once when it was already loaded from the cache", () => {
    natural = { width: 1600, height: 1200, complete: true };
    render(<ZoomableImage src="/api/rooms/demo/uploads/shot.png/raw" alt="Checkout on a phone" />);
    expect(measured()).toBe(true);
    expect(image().style.width).toBe("800px");
    expect(image()).not.toHaveClass("invisible");
  });

  it("shows while it loads, and is measured when it arrives late", () => {
    render(<ZoomableImage src="/api/rooms/demo/uploads/shot.png/raw" alt="Checkout on a phone" />);
    // Not measured yet, but on screen at fit, never hidden.
    expect(measured()).toBe(false);
    expect(image()).not.toHaveClass("invisible");
    expect(image()).toHaveClass("object-contain");

    natural = { width: 1600, height: 1200, complete: true };
    fireEvent.load(image());
    expect(measured()).toBe(true);
  });

  it("doesn't take a size of 0 as final while the image is still decoding", () => {
    natural = { width: 0, height: 0, complete: true };
    render(<ZoomableImage src="/api/rooms/demo/uploads/shot.png/raw" alt="Checkout on a phone" />);
    expect(measured()).toBe(false);
    expect(image()).not.toHaveClass("invisible");

    natural = { width: 1600, height: 1200, complete: true };
    fireEvent.load(image());
    expect(measured()).toBe(true);
  });

  it("says when it didn't load, and tries again past the failure", () => {
    render(<ZoomableImage src="/api/rooms/demo/uploads/shot.png/raw?mycelium-media=1.ab" alt="Checkout on a phone" />);
    fireEvent.error(image());
    expect(screen.getByRole("alert")).toHaveTextContent("This image didn't load.");

    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(image().getAttribute("src")).toBe("/api/rooms/demo/uploads/shot.png/raw?mycelium-media=1.ab&retry=1");

    natural = { width: 1600, height: 1200, complete: true };
    fireEvent.load(image());
    expect(measured()).toBe(true);
  });
});
