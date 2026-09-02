// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { RailSheet } from "@/components/rail-sheet";

/** The strip beside the sheet and the sheet itself, as the shell draws them:
 *  the strip stays mounted, so the control that opened the rail is the one that
 *  puts it away. */
function Shell({ onClose = vi.fn() }: { onClose?: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button onClick={() => setOpen(o => !o)}>toggle</button>
      <RailSheet
        open={open}
        onClose={() => {
          setOpen(false);
          onClose();
        }}
        side="left"
        label="Rooms"
      >
        <button>scratch</button>
      </RailSheet>
    </>
  );
}

describe("<RailSheet />", () => {
  it("holds nothing until it is opened", () => {
    render(<Shell />);
    expect(screen.queryByRole("complementary", { name: "Rooms" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "scratch" })).not.toBeInTheDocument();
  });

  it("opens from the strip, and the strip is still there to close it", async () => {
    const user = userEvent.setup();
    render(<Shell />);

    await user.click(screen.getByRole("button", { name: "toggle" }));
    expect(screen.getByRole("complementary", { name: "Rooms" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "scratch" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "toggle" }));
    expect(screen.queryByRole("complementary", { name: "Rooms" })).not.toBeInTheDocument();
  });

  it("closes on Escape and on the scrim", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<Shell onClose={onClose} />);

    await user.click(screen.getByRole("button", { name: "toggle" }));
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("complementary", { name: "Rooms" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "toggle" }));
    const scrim = document.querySelector("[aria-hidden]") as HTMLElement;
    await user.click(scrim);
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("leaves the strip's width uncovered, whichever edge it comes in from", () => {
    const { rerender } = render(
      <RailSheet open onClose={vi.fn()} side="left" label="Rooms">
        <span>rooms</span>
      </RailSheet>,
    );
    expect(screen.getByRole("complementary", { name: "Rooms" }).className).toContain("ml-12");

    rerender(
      <RailSheet open onClose={vi.fn()} side="right" label="Room inspector">
        <span>members</span>
      </RailSheet>,
    );
    expect(screen.getByRole("complementary", { name: "Room inspector" }).className).toContain("mr-12");
  });
});
