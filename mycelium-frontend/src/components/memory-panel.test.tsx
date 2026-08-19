// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
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
  MemoryDetail: () => <div data-testid="memory-detail" />,
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

vi.mock("@/lib/api", () => ({
  fetchMemories: vi.fn(),
  fetchMemory: vi.fn(),
  searchMemories: vi.fn(),
  fetchMemoryLinks: vi.fn(),
}));

import { fetchMemories, fetchMemory, fetchMemoryLinks } from "@/lib/api";

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
  });

  it("routes to full page when focusMemory targets a missing key", async () => {
    vi.mocked(fetchMemory).mockResolvedValue(null);

    render(
      <MemoryPanel
        roomName="demo"
        refreshTrigger={0}
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

    render(
      <MemoryPanel
        roomName="demo"
        refreshTrigger={0}
        focusMemory={{ key: offTree.key, nonce: 1 }}
      />,
    );

    await waitFor(() => expect(fetchMemory).toHaveBeenCalled());
    expect(await screen.findByTestId("memory-drawer")).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });
});
