// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// On the "is responding" line, an agent's @ tag opens it, the way a click in
// Members does; an engine's, an A2A member's and a person's stay plain, and so
// does every tag outside a room.

import { fireEvent, render, screen } from "@testing-library/react";
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
}));
vi.mock("@/components/agent-card", () => ({
  AgentCardHover: ({ room, handle, children }: { room: string; handle: string; children: React.ReactNode }) => (
    <>
      <span data-testid="card-for">
        {handle} in {room}
      </span>
      {children}
    </>
  ),
}));

import { AgentOpenerProvider, AgentTag, RespondingNames } from "@/components/agent-opener";
import type { Responding } from "@/lib/activity";

function inRoom(ui: React.ReactNode) {
  return render(<AgentOpenerProvider roomName="checkout">{ui}</AgentOpenerProvider>);
}

describe("an agent's @ tag", () => {
  it("opens the agent in the drawer Members opens", () => {
    inRoom(<AgentTag handle="builder" />);
    fireEvent.click(screen.getByRole("button", { name: "Open @builder" }));
    expect(screen.getByTestId("drawer").textContent).toBe("builder on studio-mini");
  });

  it("stays plain for an engine, an A2A member and a person", () => {
    inRoom(
      <>
        <AgentTag handle="aligner" /> <AgentTag handle="partner" /> <AgentTag handle="julia" />
      </>,
    );
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText(/@aligner/)).toBeTruthy();
  });

  it("stays plain outside a room", () => {
    render(<AgentTag handle="builder" />);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("opens the agent's card, for this room, on resting on it", () => {
    inRoom(<AgentTag handle="builder" />);
    expect(screen.getByTestId("card-for").textContent).toBe("builder in checkout");
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
