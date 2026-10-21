// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// An agent's @ tag opens it, the way a click in Members does; an engine's, an
// A2A member's and a person's stay plain, and so does every tag outside a room.

import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/room-data", () => ({
  useRoomRoster: () => ({
    agents: [
      { handle: "builder", adapter: "claude_code", runner: "studio-mini" },
      { handle: "aligner", adapter: "engine" },
      { handle: "partner", adapter: "a2a" },
    ],
  }),
}));
vi.mock("@/components/agent-screen", () => ({
  AgentScreenDrawer: ({ handle, runner }: { handle: string; runner: string | null }) => (
    <div data-testid="drawer">
      {handle} on {runner}
    </div>
  ),
  AgentPeek: ({ room, handle }: { room: string; handle: string }) => (
    <span data-testid="peek">
      {handle} in {room}
    </span>
  ),
}));

import { AgentOpenerProvider, AgentTag, RespondingNames } from "@/components/agent-opener";
import type { Responding } from "@/lib/activity";
import { MarkdownContent } from "@/components/markdown-content";

function inRoom(ui: React.ReactNode) {
  return render(<AgentOpenerProvider roomName="checkout">{ui}</AgentOpenerProvider>);
}

describe("an agent's @ tag", () => {
  it("opens the agent from a message, in the drawer Members opens", () => {
    inRoom(<MarkdownContent>{"@builder can you look?"}</MarkdownContent>);
    fireEvent.click(screen.getByRole("button", { name: "Open @builder" }));
    expect(screen.getByTestId("drawer").textContent).toBe("builder on studio-mini");
  });

  it("opens from a silent and an interrupting mention too", () => {
    inRoom(<MarkdownContent>{"@~builder and @!builder"}</MarkdownContent>);
    expect(screen.getAllByRole("button", { name: "Open @builder" })).toHaveLength(2);
  });

  it("stays plain for an engine, an A2A member and a person", () => {
    inRoom(<MarkdownContent>{"@aligner @partner @julia"}</MarkdownContent>);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText("@aligner")).toBeTruthy();
  });

  it("stays plain outside a room", () => {
    render(<MarkdownContent>{"@builder"}</MarkdownContent>);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("shows its terminal's last lines after resting on it, and hides them on leaving", () => {
    vi.useFakeTimers();
    try {
      inRoom(<AgentTag handle="builder" />);
      const tag = screen.getByRole("button", { name: "Open @builder" });
      fireEvent.pointerEnter(tag);
      expect(screen.queryByTestId("peek")).toBeNull();
      act(() => vi.advanceTimersByTime(400));
      expect(screen.getByTestId("peek").textContent).toBe("builder in checkout");
      fireEvent.pointerLeave(tag);
      expect(screen.queryByTestId("peek")).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("shows no peek when the pointer only passes over it", () => {
    vi.useFakeTimers();
    try {
      inRoom(<AgentTag handle="builder" />);
      const tag = screen.getByRole("button", { name: "Open @builder" });
      fireEvent.pointerEnter(tag);
      act(() => vi.advanceTimersByTime(100));
      fireEvent.pointerLeave(tag);
      act(() => vi.advanceTimersByTime(1000));
      expect(screen.queryByTestId("peek")).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("doesn't pass its click on to the row around it", () => {
    const row = vi.fn();
    inRoom(
      <div onClick={row}>
        <AgentTag handle="builder" />
      </div>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Open @builder" }));
    expect(row).not.toHaveBeenCalled();
  });
});

describe("who is responding", () => {
  const at = (...handles: string[]): Responding[] =>
    handles.map((h) => ({ handle: h, episode: null, since: 0, until: 1 }));
  const line = (group: Responding[]) => inRoom(<p data-testid="line"><RespondingNames group={group} /></p>);

  it("reads naturally for one, two and many", () => {
    const text = (group: Responding[]) => {
      const { unmount } = line(group);
      const got = screen.getByTestId("line").textContent;
      unmount();
      return got;
    };
    expect(text(at("aligner"))).toBe("@aligner");
    expect(text(at("growth", "finance"))).toBe("@growth and @finance");
    expect(text(at("a", "b", "c"))).toBe("@a, @b and 1 other");
    expect(text(at("a", "b", "c", "d"))).toBe("@a, @b and 2 others");
  });

  it("opens an agent from its name on the line", () => {
    line(at("builder", "aligner"));
    expect(screen.getAllByRole("button")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Open @builder" }));
    expect(screen.getByTestId("drawer").textContent).toBe("builder on studio-mini");
  });
});
