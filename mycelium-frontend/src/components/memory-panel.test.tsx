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

vi.mock("@/components/memory-detail", () => ({
  MemoryDetail: (props: {
    renderedBody?: string | null;
    collapseBodyAt?: number | null;
  }) => (
    <div
      data-testid="memory-detail"
      data-rendered-body={props.renderedBody ?? ""}
      data-collapse-body-at={props.collapseBodyAt ?? ""}
    />
  ),
}));

vi.mock("@/components/detail-drawer", () => ({
  DetailDrawer: ({
    open,
    children,
  }: {
    open: boolean;
    children: React.ReactNode;
  }) => (open ? <div data-testid="memory-drawer">{children}</div> : null),
}));

vi.mock("@/components/current-user", () => ({
  useCurrentUser: () => ({ principal: "alice" }),
}));

// The drawer's Discussion, stubbed: this file is about what the panel hands its
// children, and the conversation's own reads belong to its own tests.
vi.mock("@/components/task/task-conversation", () => ({
  TaskConversation: () => <div data-testid="task-conversation" />,
}));

vi.mock("@/components/room-chat-box", () => ({
  RoomChatBox: () => <div data-testid="room-chat-box" />,
}));

vi.mock("@/lib/api", () => ({
  fetchMemories: vi.fn(),
  fetchMemory: vi.fn(),
  fetchMemoryExpanded: vi.fn(),
  searchMemories: vi.fn(),
  fetchMemoryLinks: vi.fn(),
}));

import {
  fetchMemories,
  fetchMemory,
  fetchMemoryExpanded,
  fetchMemoryLinks,
} from "@/lib/api";

const EMPTY_EXPAND = { key: "", rendered: "", expansions: [], found: false };

const offTree = {
  key: "context/off-tree",
  value: { text: "not in the first page" },
  content_text: "not in the first page",
  version: 1,
  created_by: "alice",
  updated_at: "2026-01-01T00:00:00Z",
};

describe("<MemoryPanel /> peek navigation", () => {
  beforeEach(() => {
    push.mockClear();
    vi.mocked(fetchMemories).mockResolvedValue([]);
    vi.mocked(fetchMemory).mockReset();
    vi.mocked(fetchMemoryLinks).mockResolvedValue({
      key: offTree.key,
      outbound: [],
      backlinks: [],
    });
    vi.mocked(fetchMemoryExpanded).mockResolvedValue(EMPTY_EXPAND);
  });

  it("routes to full page when focusMemory targets a missing key", async () => {
    vi.mocked(fetchMemory).mockResolvedValue(null);

    renderWithSWR(
      <MemoryPanel
        roomName="demo"
        focusMemory={{ key: "missing/key", nonce: 1 }}
      />,
    );

    await act(async () => {});
    await waitFor(() =>
      expect(push).toHaveBeenCalledWith("/room/demo/memory/missing/key"),
    );
  });

  it("opens the drawer via fetch when focusMemory targets a key outside the loaded list", async () => {
    vi.mocked(fetchMemory).mockImplementation(async (room, key) => {
      expect(room).toBe("demo");
      expect(key).toBe(offTree.key);
      return offTree;
    });

    renderWithSWR(
      <MemoryPanel
        roomName="demo"
        focusMemory={{ key: offTree.key, nonce: 1 }}
      />,
    );

    await waitFor(() => expect(fetchMemory).toHaveBeenCalled());
    expect(await screen.findByTestId("memory-drawer")).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });

  it("passes the expanded body into the drawer's MemoryDetail (#599)", async () => {
    vi.mocked(fetchMemory).mockResolvedValue(offTree);
    vi.mocked(fetchMemoryExpanded).mockResolvedValue({
      key: offTree.key,
      rendered: "expanded transclusion body",
      expansions: [],
      found: true,
    });

    renderWithSWR(
      <MemoryPanel
        roomName="demo"
        focusMemory={{ key: offTree.key, nonce: 1 }}
      />,
    );

    const detail = await screen.findByTestId("memory-detail");
    await waitFor(() => expect(fetchMemoryExpanded).toHaveBeenCalledWith("demo", offTree.key));
    expect(detail).toHaveAttribute("data-rendered-body", "expanded transclusion body");
  });

  it("clamps the body only where a discussion follows it (#887)", async () => {
    // The drawer is one scroll from the metadata to the last reply, so a long
    // body is clamped behind an Expand button rather than boxed off in a
    // scrollbox of its own. A memory with no thread under it is all body, and
    // hiding half of it would buy nothing.
    vi.mocked(fetchMemory).mockResolvedValue(offTree);
    const { unmount } = renderWithSWR(
      <MemoryPanel roomName="demo" focusMemory={{ key: offTree.key, nonce: 1 }} />,
    );
    expect(await screen.findByTestId("memory-detail")).toHaveAttribute("data-collapse-body-at", "");
    unmount();

    const threaded = { ...offTree, episode: "urn:ioc:mycelium:episode:demo:t9f0" };
    vi.mocked(fetchMemory).mockResolvedValue(threaded);
    renderWithSWR(
      <MemoryPanel roomName="demo" focusMemory={{ key: threaded.key, nonce: 2 }} />,
    );
    await waitFor(() =>
      expect(screen.getByTestId("memory-detail")).not.toHaveAttribute("data-collapse-body-at", ""),
    );
    expect(screen.getByTestId("task-conversation")).toBeInTheDocument();
  });
});

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

describe("<MemoryPanel /> preview hovercard", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(fetchMemories).mockResolvedValue([treeMemory]);
    vi.mocked(fetchMemory).mockReset();
    vi.mocked(fetchMemoryExpanded).mockResolvedValue(EMPTY_EXPAND);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  // The tree opens folded to its namespaces, so reveal the folder before the leaf.
  const expandDecisions = async () => {
    fireEvent.click(await screen.findByText("decisions"));
  };

  const hoverRow = async () => {
    await expandDecisions();
    const row = (await screen.findByText("ship-it.md")).closest("div")!;
    fireEvent.mouseEnter(row);
    return row;
  };

  it("opens a preview of the memory body after the hover delay", async () => {
    renderWithSWR(<MemoryPanel roomName="demo" />);
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
    renderWithSWR(<MemoryPanel roomName="demo" />);
    const row = await hoverRow();

    await act(async () => { vi.advanceTimersByTime(200); });
    fireEvent.mouseLeave(row);
    await act(async () => { vi.advanceTimersByTime(400); });

    expect(screen.queryByTestId("memory-preview-card")).toBeNull();
  });

  it("closes the preview once the pointer leaves the row", async () => {
    renderWithSWR(<MemoryPanel roomName="demo" />);
    const row = await hoverRow();
    await act(async () => { vi.advanceTimersByTime(400); });
    expect(screen.getByTestId("memory-preview-card")).toBeInTheDocument();

    fireEvent.mouseLeave(row);
    expect(screen.queryByTestId("memory-preview-card")).toBeNull();
  });

  it("closes the preview when the row is clicked open", async () => {
    renderWithSWR(<MemoryPanel roomName="demo" />);
    await hoverRow();
    await act(async () => { vi.advanceTimersByTime(400); });

    fireEvent.click(screen.getByText("ship-it.md"));
    await waitFor(() => expect(screen.getByTestId("memory-drawer")).toBeInTheDocument());
    expect(screen.queryByTestId("memory-preview-card")).toBeNull();
  });
});
