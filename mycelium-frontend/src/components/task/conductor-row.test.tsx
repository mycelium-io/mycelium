import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { ConductorRow } from "./conductor-row";

describe("ConductorRow", () => {
  it("draws a turn as one line and keeps the prompt behind a toggle", () => {
    render(
      <ConductorRow
        line={{ event: "turn", protocol: "swarm", step: "check-in", to: "agent-2", turn: 1, cap: 4 }}
        text="swarm · check-in · turn 1 of 4 · agent-2\n\nCheck in, in two or three sentences."
      />,
    );
    const row = screen.getByTestId("conductor-row");
    expect(row.textContent).toContain("check-in");
    expect(row.textContent).toContain("agent-2");
    expect(row.textContent).toContain("turn 1 of 4");
    expect(row.textContent).not.toContain("Check in, in two or three sentences.");

    fireEvent.click(screen.getByRole("button", { name: /prompt/ }));
    expect(row.textContent).toContain("Check in, in two or three sentences.");
  });

  it("draws the end of a run as done, or as what went wrong", () => {
    const { rerender } = render(
      <ConductorRow
        line={{ event: "close", protocol: "swarm", outcome: "resolved", steps: 2, reason: "reached `done`" }}
        text="✓ swarm: resolved after 2 step(s)"
      />,
    );
    expect(screen.getByTestId("conductor-row").textContent).toContain("swarm done");
    expect(screen.queryByRole("button")).toBeNull();

    rerender(
      <ConductorRow
        line={{ event: "close", protocol: "gated", outcome: "rejected", steps: 6, reason: "hit the step cap (6)" }}
        text="✗ gated: rejected"
      />,
    );
    expect(screen.getByTestId("conductor-row").textContent).toContain("gated rejected");
    expect(screen.getByTestId("conductor-row").textContent).toContain("hit the step cap (6)");
  });
});
