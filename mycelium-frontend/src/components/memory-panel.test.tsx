// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { renderWithSWR } from "@/test/swr";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryPanel } from "@/components/memory-panel";

const push = vi.fn();

vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

vi.mock("next/link", () => ({
  default: ({
    children,
    href,
    ...props
  }: {
    children: React.ReactNode;
    href: string;
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("@/lib/api", () => ({
  fetchMemories: vi.fn(),
  searchMemories: vi.fn(),
  deleteMemory: vi.fn(),
}));

vi.mock("@/lib/clipboard", () => ({
  copyText: vi.fn(async () => undefined),
  absoluteUrl: (path: string) => `http://app${path}`,
}));

import { deleteMemory, fetchMemories } from "@/lib/api";
import { copyText } from "@/lib/clipboard";
import { memoryEditPending } from "@/lib/memory-edit-request";

const treeMemory = {
  key: "decisions/ship-it",
  value: { text: "## Ship it\n\nWe agreed to **ship** on Friday." },
  content_text: "Ship it",
  version: 3,
  created_by: "alice",
  updated_by: "bob",
  updated_at: "2026-01-01T00:00:00Z",
  tags: ["consensus"],
};

// The tree opens folded to its namespaces, so reveal the folder before the leaf.
const expandDecisions = async () => {
  fireEvent.click(await screen.findByText("decisions"));
};

describe("<MemoryPanel /> opening a memory", () => {
  beforeEach(() => {
    vi.mocked(fetchMemories).mockResolvedValue([treeMemory]);
  });

  it("opens a picked memory in the room's tabs; the panel only lists", async () => {
    const onOpenMemory = vi.fn();
    renderWithSWR(<MemoryPanel roomName="demo" onOpenMemory={onOpenMemory} />);
    await expandDecisions();

    fireEvent.click(await screen.findByText("ship-it.md"));

    expect(onOpenMemory).toHaveBeenCalledWith("decisions/ship-it");
  });

  it("opens a memory arrived at from search, and says it's done", async () => {
    const onOpenMemory = vi.fn();
    const onFocusConsumed = vi.fn();
    renderWithSWR(
      <MemoryPanel
        roomName="demo"
        onOpenMemory={onOpenMemory}
        focusKey="context/off-tree"
        onFocusConsumed={onFocusConsumed}
      />,
    );

    await waitFor(() => expect(onOpenMemory).toHaveBeenCalledWith("context/off-tree"));
    expect(onFocusConsumed).toHaveBeenCalled();
  });

  it("only reveals a memory the room already opened from a link", async () => {
    // A `[[link]]` in chat opens the memory in the room's tabs itself; the
    // tree's part is to unfold its folder and mark it.
    const onOpenMemory = vi.fn();
    const { rerender } = renderWithSWR(<MemoryPanel roomName="demo" onOpenMemory={onOpenMemory} />);
    // The tree opens folded to its namespaces.
    await screen.findByText("decisions");
    expect(screen.queryByText("ship-it.md")).not.toBeInTheDocument();

    rerender(
      <MemoryPanel
        roomName="demo"
        onOpenMemory={onOpenMemory}
        focusMemory={{ key: "decisions/ship-it", nonce: 1 }}
        activeKey="decisions/ship-it"
      />,
    );

    expect(await screen.findByText("ship-it.md")).toBeInTheDocument();
    expect(onOpenMemory).not.toHaveBeenCalled();
  });
});

describe("<MemoryPanel /> preview hovercard", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(fetchMemories).mockResolvedValue([treeMemory]);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  const hoverRow = async () => {
    await expandDecisions();
    const row = (await screen.findByText("ship-it.md")).closest("div")!;
    fireEvent.mouseEnter(row);
    return row;
  };

  it("opens a preview of the memory body after the hover delay", async () => {
    renderWithSWR(<MemoryPanel roomName="demo" onOpenMemory={vi.fn()} />);
    const row = await hoverRow();

    expect(screen.queryByTestId("memory-preview-card")).toBeNull();
    await act(async () => { vi.advanceTimersByTime(400); });

    const card = screen.getByTestId("memory-preview-card");
    expect(card).toHaveTextContent("Ship it");
    expect(card).toHaveTextContent("We agreed to ship on Friday.");
    expect(card).toHaveTextContent("v3");
    expect(card).toHaveTextContent("bob");
    expect(row).toBeInTheDocument();
  });

  it("does not open when the pointer leaves before the delay elapses", async () => {
    renderWithSWR(<MemoryPanel roomName="demo" onOpenMemory={vi.fn()} />);
    const row = await hoverRow();

    await act(async () => { vi.advanceTimersByTime(200); });
    fireEvent.mouseLeave(row);
    await act(async () => { vi.advanceTimersByTime(400); });

    expect(screen.queryByTestId("memory-preview-card")).toBeNull();
  });

  it("closes the preview once the pointer leaves the row", async () => {
    renderWithSWR(<MemoryPanel roomName="demo" onOpenMemory={vi.fn()} />);
    const row = await hoverRow();
    await act(async () => { vi.advanceTimersByTime(400); });
    expect(screen.getByTestId("memory-preview-card")).toBeInTheDocument();

    fireEvent.mouseLeave(row);
    expect(screen.queryByTestId("memory-preview-card")).toBeNull();
  });

  it("closes the preview when the row is clicked open", async () => {
    const onOpenMemory = vi.fn();
    renderWithSWR(<MemoryPanel roomName="demo" onOpenMemory={onOpenMemory} />);
    await hoverRow();
    await act(async () => { vi.advanceTimersByTime(400); });

    fireEvent.click(screen.getByText("ship-it.md"));
    expect(onOpenMemory).toHaveBeenCalledWith("decisions/ship-it");
    expect(screen.queryByTestId("memory-preview-card")).toBeNull();
  });
});

describe("<MemoryPanel /> right-click", () => {
  beforeEach(() => {
    vi.mocked(fetchMemories).mockResolvedValue([treeMemory]);
    vi.mocked(copyText).mockClear();
    vi.mocked(deleteMemory).mockReset().mockResolvedValue(undefined);
  });

  const openMenu = async () => {
    await expandDecisions();
    fireEvent.contextMenu(await screen.findByText("ship-it.md"));
  };

  it("copies the command an agent runs to read the memory", async () => {
    renderWithSWR(<MemoryPanel roomName="demo" onOpenMemory={vi.fn()} />);
    await openMenu();
    fireEvent.click(await screen.findByText("Copy command for an agent"));
    expect(copyText).toHaveBeenCalledWith("mycelium memory get decisions/ship-it --room demo");
  });

  it("opens the memory to edit it", async () => {
    const onOpenMemory = vi.fn();
    renderWithSWR(<MemoryPanel roomName="demo" onOpenMemory={onOpenMemory} />);
    await openMenu();
    fireEvent.click(await screen.findByText("Edit"));
    expect(onOpenMemory).toHaveBeenCalledWith("decisions/ship-it");
    expect(memoryEditPending("decisions/ship-it")).toBe(true);
  });

  it("asks before deleting, and deletes only on the yes", async () => {
    renderWithSWR(<MemoryPanel roomName="demo" onOpenMemory={vi.fn()} />);
    await openMenu();
    fireEvent.click(await screen.findByText("Delete…"));
    expect(await screen.findByText("Delete this memory?")).toBeInTheDocument();
    expect(deleteMemory).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(deleteMemory).toHaveBeenCalledWith("demo", "decisions/ship-it"));
  });
});
