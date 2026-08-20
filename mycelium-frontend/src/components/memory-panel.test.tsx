// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { act, screen, waitFor } from "@testing-library/react";
import { renderWithSWR } from "@/test/swr";
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
  MemoryDetail: (props: { integrity?: unknown; renderedBody?: string | null }) => (
    <div
      data-testid="memory-detail"
      data-has-integrity={props.integrity ? "yes" : "no"}
      data-rendered-body={props.renderedBody ?? ""}
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

vi.mock("@/lib/api", () => ({
  fetchMemories: vi.fn(),
  fetchMemory: vi.fn(),
  fetchMemoryExpanded: vi.fn(),
  fetchMemoryIntegrity: vi.fn(),
  searchMemories: vi.fn(),
  fetchMemoryLinks: vi.fn(),
}));

import {
  fetchMemories,
  fetchMemory,
  fetchMemoryExpanded,
  fetchMemoryIntegrity,
  fetchMemoryLinks,
} from "@/lib/api";

const EMPTY_INTEGRITY = {
  broken: [],
  orphans: [],
  roots: [],
  leaves: [],
  total_memories: 0,
  total_links: 0,
};
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
    vi.mocked(fetchMemoryIntegrity).mockResolvedValue(EMPTY_INTEGRITY);
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

  it("passes the room integrity report and expanded body into the drawer's MemoryDetail (#599)", async () => {
    vi.mocked(fetchMemory).mockResolvedValue(offTree);
    vi.mocked(fetchMemoryIntegrity).mockResolvedValue({
      broken: [
        {
          source: offTree.key,
          target: "gone",
          kind: "wikilink",
          raw: "[[gone]]",
          resolved: false,
        },
      ],
      orphans: [],
      roots: [],
      leaves: [],
      total_memories: 1,
      total_links: 1,
    });
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
    await waitFor(() => expect(detail).toHaveAttribute("data-has-integrity", "yes"));
    expect(detail).toHaveAttribute("data-rendered-body", "expanded transclusion body");
  });
});
