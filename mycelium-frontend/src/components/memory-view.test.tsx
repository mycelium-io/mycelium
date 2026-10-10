// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { fireEvent, screen, waitFor } from "@testing-library/react";
import { renderWithSWR } from "@/test/swr";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

// The detail, stubbed down to what the view hands it: the clamp, the body it
// fetched, a link to follow, and the actions at the end of its meta line.
vi.mock("@/components/memory-detail", () => ({
  MemoryDetail: (props: {
    collapseBodyAt?: number | null;
    renderedBody?: string | null;
    onNavigate: (key: string) => void;
    actions?: React.ReactNode;
  }) => (
    <div
      data-testid="memory-detail"
      data-collapse-body-at={props.collapseBodyAt ?? ""}
      data-rendered-body={props.renderedBody ?? ""}
    >
      <button onClick={() => props.onNavigate("context/linked")}>follow link</button>
      {props.actions}
    </div>
  ),
}));

vi.mock("@/components/memory-editor", () => ({
  MemoryEditor: () => <div data-testid="memory-editor" />,
}));

// The discussion, stubbed: this file is about the view, and the conversation's
// own reads belong to its own tests.
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
  fetchMemories: vi.fn().mockResolvedValue([]),
  fetchMemory: vi.fn(),
  fetchMemoryExpanded: vi.fn(),
}));

import { fetchMemory, fetchMemoryExpanded } from "@/lib/api";
import { MemoryView } from "@/components/memory-view";

const MEMORY = {
  key: "work/flip-reads",
  value: { text: "the reads have to flip behind a flag" },
  content_text: "the reads have to flip behind a flag",
  version: 1,
  created_by: "alice",
  updated_at: "2026-01-01T00:00:00Z",
};
const TASK = { ...MEMORY, episode: "urn:ioc:mycelium:episode:demo:t9f0" };

describe("<MemoryView />", () => {
  beforeEach(() => {
    vi.mocked(fetchMemory).mockReset();
    vi.mocked(fetchMemoryExpanded).mockResolvedValue({
      key: MEMORY.key,
      rendered: "",
      expansions: [],
      found: false,
    });
  });

  it("clamps the body only where a discussion follows it (#887)", async () => {
    // One scroll runs from the metadata through the body to the last reply. A
    // long body is clamped so it can't push the conversation past the fold,
    // but a memory with no thread under it is all body.
    vi.mocked(fetchMemory).mockResolvedValue(MEMORY);
    const { unmount } = renderWithSWR(
      <MemoryView roomName="demo" memoryKey={MEMORY.key} onOpenMemory={vi.fn()} />,
    );
    expect(await screen.findByTestId("memory-detail")).toHaveAttribute("data-collapse-body-at", "");
    expect(screen.queryByTestId("task-conversation")).not.toBeInTheDocument();
    unmount();

    vi.mocked(fetchMemory).mockResolvedValue(TASK);
    renderWithSWR(<MemoryView roomName="demo" memoryKey={MEMORY.key} onOpenMemory={vi.fn()} />);
    await waitFor(() =>
      expect(screen.getByTestId("memory-detail")).toHaveAttribute("data-collapse-body-at", "480"),
    );
    expect(screen.getByTestId("task-conversation")).toBeInTheDocument();
  });

  it("gives the body more room full page, where someone came to read it", async () => {
    vi.mocked(fetchMemory).mockResolvedValue(TASK);
    renderWithSWR(
      <MemoryView roomName="demo" memoryKey={MEMORY.key} onOpenMemory={vi.fn()} layout="page" />,
    );
    await waitFor(() =>
      expect(screen.getByTestId("memory-detail")).toHaveAttribute("data-collapse-body-at", "720"),
    );
  });

  it("opens an agent manifest with a discussion like any other memory", async () => {
    // A memory with an episode binding shows Discussion, regardless of namespace.
    vi.mocked(fetchMemory).mockResolvedValue({ ...TASK, key: "agents/market-data" });
    renderWithSWR(
      <MemoryView roomName="demo" memoryKey="agents/market-data" onOpenMemory={vi.fn()} />,
    );
    expect(await screen.findByTestId("task-conversation")).toBeInTheDocument();
  });

  it("shows no discussion for a row carrying the room's own live episode", async () => {
    // Reading that as a thread would empty the room's history into the view.
    vi.mocked(fetchMemory).mockResolvedValue({
      ...MEMORY,
      episode: "urn:ioc:mycelium:episode:demo:live",
    });
    renderWithSWR(<MemoryView roomName="demo" memoryKey={MEMORY.key} onOpenMemory={vi.fn()} />);
    expect(await screen.findByTestId("memory-detail")).toHaveAttribute("data-collapse-body-at", "");
    expect(screen.queryByTestId("task-conversation")).not.toBeInTheDocument();
  });

  it("shows the transcluded body, wherever it's opened (#599)", async () => {
    vi.mocked(fetchMemory).mockResolvedValue(MEMORY);
    vi.mocked(fetchMemoryExpanded).mockResolvedValue({
      key: MEMORY.key,
      rendered: "expanded transclusion body",
      expansions: [],
      found: true,
    });
    renderWithSWR(<MemoryView roomName="demo" memoryKey={MEMORY.key} onOpenMemory={vi.fn()} />);
    await waitFor(() =>
      expect(screen.getByTestId("memory-detail")).toHaveAttribute(
        "data-rendered-body",
        "expanded transclusion body",
      ),
    );
  });

  it("leaves a task's verbs to its right-click menu, in a tab and full page alike", async () => {
    vi.mocked(fetchMemory).mockResolvedValue(TASK);
    const { unmount } = renderWithSWR(
      <MemoryView roomName="demo" memoryKey={MEMORY.key} onOpenMemory={vi.fn()} />,
    );
    await screen.findByTestId("task-conversation");
    expect(screen.queryByRole("button", { name: "Ask agents" })).not.toBeInTheDocument();
    unmount();

    renderWithSWR(
      <MemoryView roomName="demo" memoryKey={MEMORY.key} onOpenMemory={vi.fn()} layout="page" />,
    );
    await screen.findByTestId("task-conversation");
    expect(screen.queryByRole("button", { name: "Ask agents" })).not.toBeInTheDocument();
  });

  it("switches to the editor and back", async () => {
    vi.mocked(fetchMemory).mockResolvedValue(MEMORY);
    renderWithSWR(<MemoryView roomName="demo" memoryKey={MEMORY.key} onOpenMemory={vi.fn()} />);
    fireEvent.click(await screen.findByText("Edit"));
    expect(screen.getByTestId("memory-editor")).toBeInTheDocument();
    expect(screen.queryByTestId("memory-detail")).not.toBeInTheDocument();
  });

  it("leaves the way back to the room to the app's breadcrumb, page or tab", async () => {
    vi.mocked(fetchMemory).mockResolvedValue(MEMORY);
    const { unmount } = renderWithSWR(
      <MemoryView roomName="demo" memoryKey={MEMORY.key} onOpenMemory={vi.fn()} layout="page" />,
    );
    await screen.findByTestId("memory-detail");
    expect(screen.queryByRole("link", { name: "demo" })).not.toBeInTheDocument();
    unmount();

    renderWithSWR(<MemoryView roomName="demo" memoryKey={MEMORY.key} onOpenMemory={vi.fn()} />);
    await screen.findByTestId("memory-detail");
    expect(screen.queryByRole("link", { name: "demo" })).not.toBeInTheDocument();
  });

  it("says plainly when a key names no memory", async () => {
    vi.mocked(fetchMemory).mockResolvedValue(null);
    renderWithSWR(
      <MemoryView roomName="demo" memoryKey="missing/key" onOpenMemory={vi.fn()} layout="page" />,
    );
    expect(await screen.findByText("No memory called missing/key")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "demo" })).toBeInTheDocument();
  });

  it("hands its guard to the room, which asks before leaving it", async () => {
    // In a tab, the room asks before leaving (it holds the guard), so a link
    // goes straight to the room rather than asking twice.
    vi.mocked(fetchMemory).mockResolvedValue(MEMORY);
    const onGuard = vi.fn();
    const onOpenMemory = vi.fn();
    renderWithSWR(
      <MemoryView
        roomName="demo"
        memoryKey={MEMORY.key}
        onOpenMemory={onOpenMemory}
        onGuard={onGuard}
      />,
    );
    fireEvent.click(await screen.findByText("follow link"));
    expect(onOpenMemory).toHaveBeenCalledWith("context/linked");
    expect(onGuard).toHaveBeenCalledWith(MEMORY.key, expect.any(Function));
  });
});
