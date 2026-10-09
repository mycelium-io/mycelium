// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

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

/** jsdom lays nothing out; the panels only need the observer to exist. */
class TestResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

function renderInspector() {
  render(<RoomInspector roomName="atlas" onOpenMemory={() => undefined} />);
  return userEvent.setup();
}

describe("<RoomInspector /> sections", () => {
  beforeEach(() => {
    vi.stubGlobal("ResizeObserver", TestResizeObserver);
  });

  it("stacks members and memory, both in view at once", () => {
    renderInspector();
    expect(screen.getByText("members panel")).toBeInTheDocument();
    expect(screen.getByText("memory panel")).toBeInTheDocument();
  });

  it("gives each section a header that folds it", () => {
    renderInspector();
    for (const label of ["Members", "Memory"]) {
      const header = screen.getByRole("button", { name: `Collapse ${label}` });
      expect(header).toHaveAttribute("aria-expanded", "true");
      expect(header).toHaveTextContent(label);
    }
  });

  it("draws one seam between the sections, to drag", () => {
    renderInspector();
    expect(screen.getAllByRole("separator")).toHaveLength(1);
  });
});

describe("<RoomInspector /> collapse", () => {
  beforeEach(() => {
    vi.stubGlobal("ResizeObserver", TestResizeObserver);
  });

  it("collapses to the icon strip and opens again from it", async () => {
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
