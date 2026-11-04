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
