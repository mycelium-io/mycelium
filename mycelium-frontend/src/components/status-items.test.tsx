// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { StatusButton } from "@/components/status-items";
import { TooltipProvider } from "@/components/ui/tooltip";

vi.mock("next/navigation", () => ({ usePathname: () => "/" }));

function renderCell(action?: string) {
  return render(
    <TooltipProvider>
      <StatusButton onClick={() => {}} tooltip="View agents" action={action}>
        <span>3 agents</span>
      </StatusButton>
    </TooltipProvider>,
  );
}

describe("<StatusButton />", () => {
  it("names the key that does the same thing, so the rail teaches the shortcut", async () => {
    const user = userEvent.setup();
    const { container } = renderCell("rail.agents");

    await user.hover(screen.getByRole("button"));

    const tooltip = await screen.findByRole("tooltip");
    expect(tooltip).toHaveTextContent("View agents");
    // Portaled out of `container`, so the cap is looked for in the document.
    expect(tooltip.querySelector("kbd")?.textContent).toBe("Alt+A");
    expect(container.querySelector("kbd")).toBeNull();
  });

  it("keeps the bare label for a cell no key reaches", async () => {
    const user = userEvent.setup();
    renderCell();

    await user.hover(screen.getByRole("button"));

    const tooltip = await screen.findByRole("tooltip");
    expect(tooltip).toHaveTextContent("View agents");
    expect(tooltip.querySelector("kbd")).toBeNull();
  });
});
