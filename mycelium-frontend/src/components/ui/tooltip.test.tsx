// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { Tooltip, TooltipProvider } from "@/components/ui/tooltip";

function renderTooltip(content?: string) {
  return render(
    <TooltipProvider>
      <Tooltip content={content}>
        <button type="button" aria-label="Dismiss">
          ×
        </button>
      </Tooltip>
    </TooltipProvider>,
  );
}

describe("<Tooltip />", () => {
  it("renders the trigger as its own element rather than wrapping it", () => {
    renderTooltip("Dismiss this notification");

    const trigger = screen.getByRole("button", { name: "Dismiss" });
    expect(trigger.tagName).toBe("BUTTON");
    expect(trigger).not.toHaveAttribute("title");
  });

  it("shows the content on hover and describes the trigger while open", async () => {
    const user = userEvent.setup();
    renderTooltip("Dismiss this notification");
    const trigger = screen.getByRole("button", { name: "Dismiss" });

    expect(screen.queryByText("Dismiss this notification")).not.toBeInTheDocument();

    await user.hover(trigger);

    const popup = await screen.findByText("Dismiss this notification");
    expect(trigger).toHaveAttribute("aria-describedby", popup.id);
  });

  it("opens on keyboard focus, so the hint is not pointer-only", async () => {
    const user = userEvent.setup();
    renderTooltip("Dismiss this notification");

    await user.tab();

    expect(await screen.findByText("Dismiss this notification")).toBeInTheDocument();
  });

  it("passes the trigger through untouched when there is nothing to say", async () => {
    const user = userEvent.setup();
    renderTooltip(undefined);
    const trigger = screen.getByRole("button", { name: "Dismiss" });

    await user.hover(trigger);

    expect(trigger).not.toHaveAttribute("aria-describedby");
    expect(trigger).not.toHaveAttribute("data-base-ui-tooltip-trigger");
  });
});
