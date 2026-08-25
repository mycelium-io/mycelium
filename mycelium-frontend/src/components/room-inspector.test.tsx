// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { act } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

// The rails fetch a room's data; this file is about the chrome around them, so
// each stands in as a marker the assertions can look for.
vi.mock("@/components/agents-panel", () => ({
  AgentsPanel: () => <div>members panel</div>,
}));
vi.mock("@/components/memory-panel", () => ({
  MemoryPanel: () => <div>memory panel</div>,
}));

import { RoomInspector } from "@/components/room-inspector";
import { TAB_LABELS_MIN_WIDTH } from "@/lib/panel-layout";

/** A ResizeObserver the test drives, standing in for a dragged panel edge. */
const observers: ((width: number) => void)[] = [];

class TestResizeObserver {
  constructor(private callback: ResizeObserverCallback) {
    observers.push(width => {
      this.callback(
        [{ contentRect: { width } } as ResizeObserverEntry],
        this as unknown as ResizeObserver,
      );
    });
  }
  observe() {}
  unobserve() {}
  disconnect() {}
}

async function railWidth(width: number): Promise<void> {
  await act(async () => {
    for (const resize of observers) resize(width);
  });
}

function renderInspector() {
  render(<RoomInspector roomName="atlas" />);
  return userEvent.setup();
}

describe("<RoomInspector /> tab strip", () => {
  beforeEach(() => {
    observers.length = 0;
    vi.stubGlobal("ResizeObserver", TestResizeObserver);
  });

  it("labels the tabs while the rail is wide enough to hold the words", async () => {
    renderInspector();
    await railWidth(TAB_LABELS_MIN_WIDTH + 40);

    for (const label of ["Members", "Memory"]) {
      expect(screen.getByRole("button", { name: label })).toHaveTextContent(label);
    }
  });

  it("drops to icons alone once the rail is too narrow for them", async () => {
    renderInspector();
    await railWidth(TAB_LABELS_MIN_WIDTH - 40);

    for (const label of ["Members", "Memory"]) {
      // Still addressable by name — the label moved to the accessible name and
      // the tooltip rather than disappearing.
      expect(screen.getByRole("button", { name: label })).toHaveTextContent("");
    }
  });

  it("switches tabs the same way at either width", async () => {
    const user = renderInspector();
    await railWidth(TAB_LABELS_MIN_WIDTH - 40);

    await user.click(screen.getByRole("button", { name: "Memory" }));
    expect(screen.getByText("memory panel")).toBeInTheDocument();
  });
});

describe("<RoomInspector /> collapse", () => {
  beforeEach(() => {
    observers.length = 0;
    vi.stubGlobal("ResizeObserver", TestResizeObserver);
  });

  it("collapses to the icon strip and reopens on the tab you clicked", async () => {
    const user = renderInspector();
    expect(screen.getByText("members panel")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^Collapse the rail/ }));
    expect(screen.queryByText("members panel")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Memory" }));
    expect(screen.getByText("memory panel")).toBeInTheDocument();
  });

  it("names the keybind on the toggle, since the badge can't draw it", async () => {
    const user = renderInspector();

    const collapse = screen.getByRole("button", { name: "Collapse the rail (\\)" });
    await user.click(collapse);
    expect(screen.getByRole("button", { name: "Expand the rail (\\)" })).toBeInTheDocument();
  });
});
