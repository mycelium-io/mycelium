// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// A member's card: what it says for an agent, a person and an engine, and which
// agents' screens it asks for (only one of yours, in a state its screen says
// something in).

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PresenceMember } from "@/lib/api";

let presence = new Map<string, PresenceMember>();
vi.mock("@/lib/room-data", () => ({
  useRoomRoster: () => ({
    agents: [
      { handle: "builder", adapter: "claude_code", runner: "mine", framework: "claude", owner: "morgan", description: "Writes the checkout code." },
      { handle: "designer", adapter: "claude_code", runner: "jamies-mbp", framework: "claude", owner: "jamie", description: "Designs the screens." },
      { handle: "conductor", adapter: "engine", kind: "conductor", description: "Walks a flow." },
    ],
    people: [{ handle: "morgan" }],
    presence,
    floors: new Map(),
  }),
  useRoomBoard: () => ({ board: { epics: [], tasks: [{ title: "Add Apple Pay", holder: "@builder", assignee: null }] } }),
}));
vi.mock("@/lib/runners", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/runners")>()),
  useRunners: () => ({ runners: [{ id: "mine", label: "morgans-mbp", machine: null }], connected: [], loading: false, refresh: () => {} }),
}));
vi.mock("@/lib/people", () => ({
  useNames: () => new Map([["morgan", "Morgan Reyes"]]),
  nameOf: (names: Map<string, string>, handle: string) => names.get(handle),
}));
vi.mock("@/components/agent-opener", () => ({ useAgentOpener: () => ({ room: "checkout", open: vi.fn() }) }));
vi.mock("@/components/agent-screen", () => ({
  ScreenLines: ({ handle }: { handle: string }) => <div data-testid="screen">{handle}</div>,
}));

import { AgentCard, AgentCardHover, CARD_DELAY_MS } from "@/components/agent-card";

const card = (handle: string) => render(<AgentCard room="checkout" handle={handle} onRestart={() => {}} />);
const herdr = (handle: string, status: string, extra: Partial<PresenceMember> = {}): [string, PresenceMember] => [
  handle,
  { handle, kind: "herdr", last_seen: null, status, ...extra },
];

beforeEach(() => {
  presence = new Map();
});

describe("an agent's card", () => {
  it("says who it is, whose it is, where it runs and what it's on", () => {
    presence = new Map([herdr("builder", "working")]);
    card("builder");
    expect(screen.getByText("Working")).toBeInTheDocument();
    expect(screen.getByText("Writes the checkout code.")).toBeInTheDocument();
    expect(screen.getByText("Morgan Reyes")).toBeInTheDocument();
    expect(screen.getByText("@morgan")).toBeInTheDocument();
    expect(screen.getByText("morgans-mbp · claude")).toBeInTheDocument();
    expect(screen.getByText("Add Apple Pay")).toBeInTheDocument();
  });

  it("shows the screen of one of your agents while it's working or waiting", () => {
    presence = new Map([herdr("builder", "blocked")]);
    card("builder");
    expect(screen.getByText("Waiting for input")).toBeInTheDocument();
    expect(screen.getByTestId("screen").textContent).toBe("builder");
    expect(screen.getByRole("button", { name: /Terminal/ })).toBeInTheDocument();
  });

  it("shows no screen while your agent is idle", () => {
    presence = new Map([herdr("builder", "idle")]);
    card("builder");
    expect(screen.queryByTestId("screen")).toBeNull();
  });

  it("never asks for someone else's agent's screen, and offers no terminal", () => {
    presence = new Map([herdr("designer", "working")]);
    card("designer");
    expect(screen.getByText("Working")).toBeInTheDocument();
    expect(screen.queryByTestId("screen")).toBeNull();
    expect(screen.queryByRole("button", { name: /Terminal/ })).toBeNull();
    expect(screen.getByRole("button", { name: /Message/ })).toBeInTheDocument();
  });

  it("says it can't reply, and why, once the runner reports it", () => {
    presence = new Map([herdr("builder", "idle", { can_reply: false, cant_reply_why: "Signed out of the hub on morgans-mbp" })]);
    card("builder");
    expect(screen.getByText("Can't reply")).toBeInTheDocument();
    expect(screen.getByText("Signed out of the hub on morgans-mbp")).toBeInTheDocument();
    expect(screen.getByTestId("screen")).toBeInTheDocument();
  });
});

describe("a person's and an engine's card", () => {
  it("gives a person Message only, and no screen", () => {
    card("morgan");
    expect(screen.getByText("Morgan Reyes")).toBeInTheDocument();
    expect(screen.queryByTestId("screen")).toBeNull();
    expect(screen.queryByRole("button", { name: /Terminal/ })).toBeNull();
    expect(screen.getByRole("button", { name: /Message/ })).toBeInTheDocument();
  });

  it("says an engine runs on the hub, with no screen", () => {
    presence = new Map([herdr("conductor", "working")]);
    card("conductor");
    expect(screen.getByText("the hub")).toBeInTheDocument();
    expect(screen.queryByTestId("screen")).toBeNull();
  });
});

describe("the card on a name", () => {
  it("gets out of the way when the name is clicked, until the pointer leaves it", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(
      <AgentCardHover room="checkout" handle="builder">
        <button type="button" onClick={onClick}>
          builder
        </button>
      </AgentCardHover>,
    );
    const name = screen.getByRole("button", { name: "builder" });

    await user.hover(name);
    expect(await screen.findByText("Writes the checkout code.", undefined, { timeout: 2000 })).toBeInTheDocument();

    // The click still does what the name does, and the card goes at once.
    await user.click(name);
    expect(onClick).toHaveBeenCalledOnce();
    await waitFor(() => expect(screen.queryByText("Writes the checkout code.")).toBeNull());

    // Resting on the name again doesn't bring it back over what the click opened.
    await new Promise(r => setTimeout(r, CARD_DELAY_MS + 200));
    expect(screen.queryByText("Writes the checkout code.")).toBeNull();

    // Once the pointer has left, the name opens its card again.
    await user.unhover(name);
    await user.hover(name);
    expect(await screen.findByText("Writes the checkout code.", undefined, { timeout: 2000 })).toBeInTheDocument();
  });
});
