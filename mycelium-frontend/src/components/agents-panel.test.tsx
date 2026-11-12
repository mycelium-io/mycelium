// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AgentRow } from "@/components/agents-panel";
import type { AgentSummary } from "@/lib/api";

const builder = { handle: "builder", adapter: "claude" } as unknown as AgentSummary;

function row(onOpen = vi.fn()) {
  render(<AgentRow agent={builder} groupOwner={null} marked={false} onOpen={onOpen} />);
  return { onOpen, el: screen.getByRole("button", { name: "Watch @builder's terminal" }) };
}

describe("an agent's row in Members", () => {
  it("opens its terminal on a click", () => {
    const { onOpen, el } = row();
    fireEvent.click(el);
    expect(onOpen).toHaveBeenCalledOnce();
  });

  it("leaves a right-click to the row's menu, however the browser sends it", () => {
    const { onOpen, el } = row();
    // A secondary button, a Mac's Ctrl-click, and a click that comes with the
    // menu opening.
    fireEvent.click(el, { button: 2 });
    fireEvent.click(el, { button: 0, ctrlKey: true });
    fireEvent.contextMenu(el);
    fireEvent.click(el, { button: 0 });
    expect(onOpen).not.toHaveBeenCalled();
  });
});
