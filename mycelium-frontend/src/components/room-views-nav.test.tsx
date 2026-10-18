// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// The room's views under the room in the Rooms rail, apart from the tabs you open.

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { RoomViewIcons, RoomViewsList } from "./room-views-nav";

describe("<RoomViewIcons />", () => {
  it("folds every view to an icon under the room, marks the one shown, and picks one on a click", async () => {
    const onView = vi.fn();
    render(<RoomViewIcons view="board" onView={onView} channelCount={null} />);
    const nav = screen.getByRole("navigation", { name: "Room views" });
    expect([...nav.querySelectorAll("button")].map(b => b.getAttribute("aria-label"))).toEqual([
      "Channel",
      "Stream",
      "Board",
      "Files",
      "Schedules",
    ]);
    expect(screen.getByRole("button", { name: "Board" })).toHaveAttribute("aria-current", "page");
    await userEvent.click(screen.getByRole("button", { name: "Files" }));
    expect(onView).toHaveBeenCalledWith("files");
  });
});

describe("<RoomViewsList />", () => {
  it("lists the room's views in order, marks the one shown, and counts the Channel", () => {
    render(<RoomViewsList view="board" onView={vi.fn()} channelCount={40} />);
    const nav = screen.getByRole("navigation", { name: "Room views" });
    const rows = nav.querySelectorAll("button");
    // Each row's name; its key hint shows on hover.
    expect([...rows].map(r => r.querySelector(".truncate")?.textContent)).toEqual([
      "Channel",
      "Stream",
      "Board",
      "Files",
      "Schedules",
    ]);
    expect(screen.getByRole("button", { name: /Board/ })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("button", { name: /Channel/ })).toHaveTextContent("40");
  });

  it("shows a view when its row is picked", async () => {
    const onView = vi.fn();
    render(<RoomViewsList view="channel" onView={onView} channelCount={null} />);
    await userEvent.click(screen.getByRole("button", { name: /Stream/ }));
    expect(onView).toHaveBeenCalledWith("stream");
  });

  it("keeps the tour's mark on the Board row", () => {
    render(<RoomViewsList view="channel" onView={vi.fn()} channelCount={null} />);
    expect(document.querySelector('[data-tour="tab-board"]')).toHaveTextContent("Board");
  });
});
