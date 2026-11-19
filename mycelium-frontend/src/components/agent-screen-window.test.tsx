// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// An agent's terminal opens as a window: the first time full height on the
// right, after that where that agent's was left, never off-screen. Nothing
// dims behind it, and Esc or × closes it.

import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/components/agent-screen", () => ({
  AgentScreen: ({ handle, view }: { handle: string; view?: string }) => (
    <pre aria-label="Its terminal" data-view={view}>
      {handle} is working
    </pre>
  ),
}));

// What the app answers for the agent's session: nothing yet, a session, or why there's none.
let read: { session: object | null; unavailable: string | null; error: null } = {
  session: null,
  unavailable: null,
  error: null,
};
vi.mock("@/lib/agent-session", () => ({ useAgentSession: () => read }));
vi.mock("@/lib/desktop", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/desktop")>()),
  useIsDesktop: () => true,
}));
// The room's agents, for the list down the window's side: two agents and an
// engine, which has no terminal. Subagents have no manifest; they're in the
// room's record of them, one running under builder and one ended.
vi.mock("@/lib/room-data", () => ({
  useRoomRoster: () => ({
    agents: [
      { handle: "builder", adapter: "claude" },
      { handle: "reviewer", adapter: "codex" },
      { handle: "conductor", adapter: "engine" },
    ],
    presence: new Map([["builder", { handle: "builder", status: "working" }]]),
  }),
  useRoomSubagents: () =>
    new Map([
      ["builder:tests", { handle: "builder:tests", parent: "builder", name: "tests", state: "working" }],
      ["builder:old", { handle: "builder:old", parent: "builder", name: "old", state: "ended" }],
    ]),
}));

import { AgentScreenWindow } from "@/components/agent-screen-window";
import { defaultRect, saveRect, savedRect } from "@/lib/terminal-window";

function open(onClose = vi.fn()) {
  const view = render(
    <div>
      <p>The channel</p>
      <AgentScreenWindow room="checkout" handle="builder" onClose={onClose} />
    </div>,
  );
  return { ...view, onClose };
}

const terminal = () => screen.getByRole("region", { name: "@builder's terminal" });
const viewport = () => ({ width: window.innerWidth, height: window.innerHeight });

beforeEach(() => {
  window.localStorage.clear();
  read = { session: null, unavailable: null, error: null };
});

const shown = () => screen.getByLabelText("Its terminal").getAttribute("data-view");
const pick = (name: string) => fireEvent.click(screen.getByRole("radio", { name }));

describe("the list of the room's agents down the window's side", () => {
  const list = () => screen.getByRole("navigation", { name: "Agents in this room" });

  it("lists the room's agents, each running subagent under the parent its record names, and no engine", () => {
    render(<AgentScreenWindow room="checkout" handle="builder" onClose={vi.fn()} onSwitch={vi.fn()} />);
    const names = Array.from(list().querySelectorAll("button")).map((b) => b.getAttribute("aria-label"));
    expect(names).toEqual(["@builder, Working", "@builder:tests, Working", "@reviewer, Not running"]);
    expect(screen.getByRole("button", { name: "@builder, Working" })).toHaveAttribute("aria-current", "true");
  });

  it("switches the window to the agent clicked, and a subagent's click to its parent's screen", () => {
    const onSwitch = vi.fn();
    render(<AgentScreenWindow room="checkout" handle="reviewer" onClose={vi.fn()} onSwitch={onSwitch} />);
    fireEvent.click(screen.getByRole("button", { name: "@builder:tests, Working" }));
    expect(onSwitch).toHaveBeenLastCalledWith("builder");
    fireEvent.click(screen.getByRole("button", { name: "@reviewer, Not running" }));
    expect(onSwitch).toHaveBeenLastCalledWith("reviewer");
  });

  it("doesn't carry a pick made for one agent over to the next", () => {
    read = { session: null, unavailable: "No converter for this CLI.", error: null };
    const { rerender } = render(
      <AgentScreenWindow room="checkout" handle="builder" onClose={vi.fn()} onSwitch={vi.fn()} />,
    );
    pick("What it's doing");
    expect(screen.getByLabelText("Its terminal").getAttribute("data-view")).toBe("rendered");
    rerender(<AgentScreenWindow room="checkout" handle="reviewer" onClose={vi.fn()} onSwitch={vi.fn()} />);
    expect(screen.getByLabelText("Its terminal").getAttribute("data-view")).toBe("terminal");
  });

  it("folds to avatars, and stays folded the next time a window opens", () => {
    const { unmount } = render(
      <AgentScreenWindow room="checkout" handle="builder" onClose={vi.fn()} onSwitch={vi.fn()} />,
    );
    expect(screen.getByText("reviewer")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Fold the agents list" }));
    expect(screen.queryByText("reviewer")).toBeNull();
    unmount();
    render(<AgentScreenWindow room="checkout" handle="builder" onClose={vi.fn()} onSwitch={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Show the room's agents" })).toBeInTheDocument();
  });

  it("isn't there when nothing can switch the window", () => {
    open();
    expect(screen.queryByRole("navigation", { name: "Agents in this room" })).toBeNull();
  });
});

describe("the window's rendered view and terminal", () => {
  it("has no toggle until the app has answered for the agent", () => {
    open();
    expect(screen.queryByRole("radiogroup", { name: "Show" })).toBeNull();
    expect(shown()).toBe("terminal");
  });

  it("opens on the rendered view, and remembers a switch to the terminal for every agent", () => {
    read = { session: { entries: [] }, unavailable: null, error: null };
    const { unmount } = open();
    expect(shown()).toBe("rendered");
    pick("Terminal");
    expect(shown()).toBe("terminal");
    unmount();
    open();
    expect(screen.getByRole("radio", { name: "Terminal" })).toHaveAttribute("aria-checked", "true");
  });

  it("opens on the terminal when there's no session to draw, and a pick there isn't remembered", () => {
    read = { session: null, unavailable: "no_converter", error: null };
    const { unmount } = open();
    expect(shown()).toBe("terminal");
    // Picking the rendered side shows why; the other agents' windows keep theirs.
    pick("What it's doing");
    expect(shown()).toBe("rendered");
    pick("Terminal");
    unmount();
    read = { session: { entries: [] }, unavailable: null, error: null };
    open();
    expect(shown()).toBe("rendered");
  });
});

describe("an agent's terminal window", () => {
  it("opens the first time on the right, as tall as the room, with nothing over the room", () => {
    open();
    const first = defaultRect(viewport());
    expect(terminal().parentElement).toBe(document.body);
    expect(terminal().style).toMatchObject({ left: `${first.x}px`, top: `${first.y}px`, height: `${first.height}px` });
    expect(screen.getByText("builder is working")).toBeTruthy();
    expect(document.querySelector("[aria-hidden].fixed.inset-0")).toBeNull();
    // There's nothing to dock it to.
    expect(screen.queryByRole("button", { name: /Dock|Pop out/ })).toBeNull();
  });

  it("opens where this agent's was left", () => {
    saveRect("builder", { x: 120, y: 80, width: 500, height: 600 });
    open();
    expect(terminal().style).toMatchObject({ left: "120px", top: "80px", width: "500px", height: "600px" });
  });

  it("opens on screen even if it was left somewhere that's gone", () => {
    saveRect("builder", { x: 5000, y: 3000, width: 500, height: 600 });
    open();
    expect(parseFloat(terminal().style.left)).toBeLessThan(window.innerWidth);
    expect(parseFloat(terminal().style.top)).toBeLessThan(window.innerHeight);
  });

  it("moves when dragged by its header, and remembers where it went", () => {
    saveRect("builder", { x: 200, y: 100, width: 500, height: 600 });
    open();
    const header = terminal().querySelector("header")!;
    header.setPointerCapture = vi.fn();
    fireEvent.pointerDown(header, { clientX: 250, clientY: 110, pointerId: 1 });
    fireEvent.pointerMove(header, { clientX: 150, clientY: 140, pointerId: 1 });
    fireEvent.pointerUp(header, { pointerId: 1 });
    expect(terminal().style).toMatchObject({ left: "100px", top: "130px" });
    expect(savedRect("builder")).toMatchObject({ x: 100, y: 130 });
  });

  it("resizes from any edge or corner, and remembers its size", () => {
    saveRect("builder", { x: 200, y: 100, width: 500, height: 600 });
    open();
    const grab = (edge: string, dx: number, dy: number) => {
      const handle = terminal().querySelector<HTMLElement>(`[data-edge="${edge}"]`)!;
      handle.setPointerCapture = vi.fn();
      fireEvent.pointerDown(handle, { clientX: 300, clientY: 300, pointerId: 1 });
      fireEvent.pointerMove(handle, { clientX: 300 + dx, clientY: 300 + dy, pointerId: 1 });
      fireEvent.pointerUp(handle, { pointerId: 1 });
    };
    expect(terminal().querySelectorAll("[data-edge]")).toHaveLength(8);
    grab("w", -50, 0);
    expect(terminal().style).toMatchObject({ left: "150px", width: "550px" });
    grab("n", 0, 40);
    expect(terminal().style).toMatchObject({ top: "140px", height: "560px" });
    grab("se", 20, -60);
    expect(terminal().style).toMatchObject({ width: "570px", height: "500px" });
    expect(savedRect("builder")).toEqual({ x: 150, y: 140, width: 570, height: 500 });
  });

  it("closes on Esc and on ×, but not on an Esc something else took", () => {
    const { onClose } = open();
    const taken = new KeyboardEvent("keydown", { key: "Escape", cancelable: true });
    taken.preventDefault();
    document.dispatchEvent(taken);
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.click(screen.getByRole("button", { name: "Close @builder's terminal" }));
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});
