// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// An agent's terminal peeks in over the workspace's right side, with nothing
// dimmed behind it, and pops out into a window that opens where that agent's
// was last left. Esc and × close it.

import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/components/agent-screen", () => ({
  AgentScreen: ({ handle }: { handle: string }) => <pre aria-label="Its terminal">{handle} is working</pre>,
}));

import { AgentScreenPeek } from "@/components/agent-screen-peek";
import { PEEK_LAYER_ID, saveRect } from "@/lib/terminal-window";

function peek(onClose = vi.fn()) {
  const view = render(
    <div>
      <p>The channel</p>
      <div id={PEEK_LAYER_ID} data-testid="layer" />
      <AgentScreenPeek room="checkout" handle="builder" onClose={onClose} />
    </div>,
  );
  return { ...view, onClose };
}

const terminal = () => screen.getByRole("region", { name: "@builder's terminal" });

beforeEach(() => window.localStorage.clear());

describe("the peek", () => {
  it("shows the terminal in the workspace's layer, with nothing over the room", () => {
    peek();
    expect(within(screen.getByTestId("layer")).getByRole("region", { name: "@builder's terminal" })).toBeTruthy();
    expect(screen.getByText("builder is working")).toBeTruthy();
    // No backdrop: the channel is still the page's to click.
    expect(document.querySelector("[aria-hidden].fixed.inset-0")).toBeNull();
  });

  it("closes on Esc and on ×, but not on an Esc something else took", () => {
    const { onClose } = peek();
    const taken = new KeyboardEvent("keydown", { key: "Escape", cancelable: true });
    taken.preventDefault();
    document.dispatchEvent(taken);
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.click(screen.getByRole("button", { name: "Close @builder's terminal" }));
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});

describe("popped out", () => {
  it("becomes a window where this agent's was left, and docks back", () => {
    saveRect("builder", { x: 120, y: 80, width: 500, height: 600 });
    peek();
    fireEvent.click(screen.getByRole("button", { name: "Pop out @builder's terminal" }));
    expect(terminal().parentElement).toBe(document.body);
    expect(terminal().style).toMatchObject({ left: "120px", top: "80px", width: "500px", height: "600px" });

    fireEvent.click(screen.getByRole("button", { name: "Dock @builder's terminal" }));
    expect(within(screen.getByTestId("layer")).getByRole("region", { name: "@builder's terminal" })).toBeTruthy();
  });

  it("opens on screen even if it was left somewhere that's gone", () => {
    saveRect("builder", { x: 5000, y: 3000, width: 500, height: 600 });
    peek();
    fireEvent.click(screen.getByRole("button", { name: "Pop out @builder's terminal" }));
    expect(parseFloat(terminal().style.left)).toBeLessThan(window.innerWidth);
    expect(parseFloat(terminal().style.top)).toBeLessThan(window.innerHeight);
  });
});
