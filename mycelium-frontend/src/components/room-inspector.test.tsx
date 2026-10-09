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

// jsdom lays nothing out, so the real panels can't measure a size to fold to.
// This stand-in keeps their contract — a panel handle that collapses and
// expands, and `onResize` with the size it lands at — which is all the rail's
// own logic reads.
vi.mock("react-resizable-panels", async () => {
  const React = await import("react");
  type Size = { inPixels: number; asPercentage: number };
  type Props = {
    children?: React.ReactNode;
    className?: string;
    panelRef?: React.RefObject<unknown>;
    collapsedSize?: number;
    onResize?: (size: Size) => void;
  };
  function Panel({ children, className, panelRef, collapsedSize = 0, onResize }: Props) {
    const [collapsed, setCollapsed] = React.useState(false);
    const report = React.useRef(onResize);
    report.current = onResize;
    React.useEffect(() => {
      report.current?.({ inPixels: collapsed ? collapsedSize : 300, asPercentage: 50 });
    }, [collapsed, collapsedSize]);
    React.useImperativeHandle(panelRef as React.Ref<unknown>, () => ({
      collapse: () => setCollapsed(true),
      expand: () => setCollapsed(false),
      isCollapsed: () => collapsed,
    }));
    return <div className={className}>{children}</div>;
  }
  return {
    Group: ({ children, className }: Props) => <div className={className}>{children}</div>,
    Panel,
    Separator: () => <div role="separator" />,
    usePanelRef: () => React.useRef(null),
    useDefaultLayout: () => ({}),
  };
});

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

  it("keeps a folded section folded, even one that isn't the section last asked for", async () => {
    const user = renderInspector();
    // Members is the section named by default; folding Memory must not move
    // that, or the reveal would open Memory straight back up.
    await user.click(screen.getByRole("button", { name: "Collapse Memory" }));
    expect(await screen.findByRole("button", { name: "Expand Memory" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(screen.queryByText("memory panel")).not.toBeInTheDocument();
    expect(screen.getByText("members panel")).toBeInTheDocument();
  });

  it("opens a folded section when it is asked for", async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <RoomInspector roomName="atlas" tab="memory" reveal={0} onOpenMemory={() => undefined} />,
    );
    await user.click(screen.getByRole("button", { name: "Collapse Memory" }));
    await screen.findByRole("button", { name: "Expand Memory" });

    rerender(<RoomInspector roomName="atlas" tab="memory" reveal={1} onOpenMemory={() => undefined} />);
    expect(await screen.findByText("memory panel")).toBeInTheDocument();
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
