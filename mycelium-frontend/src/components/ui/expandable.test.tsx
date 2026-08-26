// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { Expandable } from "@/components/ui/expandable";

// jsdom lays nothing out, so `scrollHeight` is 0 for every element. The
// component's whole decision is a measurement, so the test supplies one.
let restore: (() => void) | null = null;
function measuring(px: number) {
  const original = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollHeight");
  Object.defineProperty(HTMLElement.prototype, "scrollHeight", {
    configurable: true,
    get: () => px,
  });
  restore = () => {
    if (original) Object.defineProperty(HTMLElement.prototype, "scrollHeight", original);
  };
}

afterEach(() => {
  restore?.();
  restore = null;
});

describe("<Expandable />", () => {
  it("leaves short content alone — no clamp, nothing to click", async () => {
    measuring(120);
    render(
      <Expandable collapsedHeight={320} label="the task body">
        <p>short enough to read</p>
      </Expandable>,
    );
    expect(await screen.findByText("short enough to read")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("clamps long content behind Expand, and lets it back out", async () => {
    measuring(900);
    render(
      <Expandable collapsedHeight={320} label="the task body">
        <p>a very long task body</p>
      </Expandable>,
    );

    const expand = await screen.findByRole("button", { name: "Expand the task body" });
    const clamped = screen.getByText("a very long task body").parentElement!;
    expect(clamped).toHaveStyle({ maxHeight: "320px", overflow: "hidden" });
    expect(expand).toHaveAttribute("aria-expanded", "false");

    await userEvent.click(expand);

    // Expanding releases the clamp rather than opening a scrollbox: the point
    // is that the surface keeps exactly one scroll.
    expect(clamped.style.maxHeight).toBe("");
    expect(clamped.style.overflow).toBe("");
    expect(
      screen.getByRole("button", { name: "Collapse the task body" }),
    ).toHaveAttribute("aria-expanded", "true");
  });
});
