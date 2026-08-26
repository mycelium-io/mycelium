// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { screen, waitFor } from "@testing-library/react";
import { renderWithSWR } from "@/test/swr";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock("@/components/memory-detail", () => ({
  MemoryDetail: (props: { collapseBodyAt?: number | null }) => (
    <div data-testid="memory-detail" data-collapse-body-at={props.collapseBodyAt ?? ""} />
  ),
}));

// The page's Discussion, stubbed: this file is about the page's layout, and the
// conversation's own reads belong to its own tests.
vi.mock("@/components/task/task-conversation", () => ({
  TaskConversation: () => <div data-testid="task-conversation" />,
}));

vi.mock("@/components/room-chat-box", () => ({
  RoomChatBox: () => <div data-testid="room-chat-box" />,
}));

vi.mock("@/components/current-user", () => ({
  useCurrentUser: () => ({ principal: "alice" }),
}));

vi.mock("@/lib/api", () => ({
  logFetchError: () => () => undefined,
  fetchMemory: vi.fn(),
  fetchMemoryExpanded: vi.fn(),
  fetchMemoryIntegrity: vi.fn(),
}));

import { fetchMemory, fetchMemoryExpanded, fetchMemoryIntegrity } from "@/lib/api";
import { MemoryPageView } from "@/components/memory-page-view";

const MEMORY = {
  key: "work/flip-reads",
  value: { text: "the reads have to flip behind a flag" },
  content_text: "the reads have to flip behind a flag",
  version: 1,
  created_by: "alice",
  updated_at: "2026-01-01T00:00:00Z",
};

describe("<MemoryPageView />", () => {
  beforeEach(() => {
    vi.mocked(fetchMemoryExpanded).mockResolvedValue({
      key: MEMORY.key,
      rendered: "",
      expansions: [],
      found: false,
    });
    vi.mocked(fetchMemoryIntegrity).mockResolvedValue({
      broken: [],
      orphans: [],
      roots: [],
      leaves: [],
      total_memories: 1,
      total_links: 0,
    });
  });

  it("clamps the body only where a discussion follows it (#887)", async () => {
    // The page is one scroll from the metadata through the body to the last
    // reply. A long body is clamped behind an Expand button so it cannot push
    // the conversation past the fold — but a memory with no thread under it is
    // all body, and hiding half of it would buy nothing.
    vi.mocked(fetchMemory).mockResolvedValue(MEMORY);
    const { unmount } = renderWithSWR(<MemoryPageView roomName="demo" memoryKey={MEMORY.key} />);
    expect(await screen.findByTestId("memory-detail")).toHaveAttribute("data-collapse-body-at", "");
    expect(screen.queryByTestId("task-conversation")).not.toBeInTheDocument();
    unmount();

    vi.mocked(fetchMemory).mockResolvedValue({
      ...MEMORY,
      episode: "urn:ioc:mycelium:episode:demo:t9f0",
    });
    renderWithSWR(<MemoryPageView roomName="demo" memoryKey={MEMORY.key} />);
    await waitFor(() =>
      expect(screen.getByTestId("memory-detail")).not.toHaveAttribute("data-collapse-body-at", ""),
    );
    expect(screen.getByTestId("task-conversation")).toBeInTheDocument();
  });

  it("shows no discussion for a row carrying the room's own live episode", async () => {
    // Reading that as a thread would empty the room's history into the page.
    vi.mocked(fetchMemory).mockResolvedValue({
      ...MEMORY,
      episode: "urn:ioc:mycelium:episode:demo:live",
    });
    renderWithSWR(<MemoryPageView roomName="demo" memoryKey={MEMORY.key} />);
    expect(await screen.findByTestId("memory-detail")).toHaveAttribute("data-collapse-body-at", "");
    expect(screen.queryByTestId("task-conversation")).not.toBeInTheDocument();
  });
});
