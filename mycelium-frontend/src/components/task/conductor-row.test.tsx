import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { ConductorRow } from "./conductor-row";

describe("ConductorRow", () => {
  it("draws a turn as one line and keeps the prompt behind a toggle", () => {
    render(
      <ConductorRow
        line={{ event: "turn", protocol: "fan-out", step: "gather", to: "agent-2", turn: 1, cap: 6 }}
        text="fan-out · gather · turn 1 of 6 · agent-2\n\nAnswer the lead, in two or three sentences."
      />,
    );
    const row = screen.getByTestId("conductor-row");
    expect(row.textContent).toContain("gather");
    expect(row.textContent).toContain("agent-2");
    expect(row.textContent).toContain("turn 1 of 6");
    expect(row.textContent).not.toContain("Answer the lead, in two or three sentences.");

    fireEvent.click(screen.getByRole("button", { name: /prompt/ }));
    expect(row.textContent).toContain("Answer the lead, in two or three sentences.");
  });

  it("draws a step put to everyone at once as one row naming each member", () => {
    render(
      <ConductorRow
        line={{ event: "turn", protocol: "fan-out", step: "gather", to: "pm", turn: 2, cap: 6 }}
        members={["pm", "web", "api"]}
        text="fan-out · gather · turn 2 of 6 · pm"
      />,
    );
    expect(screen.getByTestId("conductor-row").textContent).toContain("gather → pm, web, api · turn 2 of 6");
  });

  it("draws the end of a run as done, or as what went wrong", () => {
    const { rerender } = render(
      <ConductorRow
        line={{ event: "close", protocol: "fan-out", outcome: "resolved", steps: 2, reason: "reached `done`" }}
        text="✓ fan-out: resolved after 2 step(s)"
      />,
    );
    expect(screen.getByTestId("conductor-row").textContent).toContain("fan-out done");
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
