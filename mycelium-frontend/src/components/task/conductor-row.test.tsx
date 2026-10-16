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

  it("draws a pick as a scorecard: who rated what, the pick, and who's short", () => {
    render(
      <ConductorRow
        line={{
          event: "select",
          step: "pick",
          next: "repair",
          select: {
            outcome: "infeasible",
            pick: "B",
            text: "10% off",
            threshold: 70,
            options: [
              { label: "A", text: "20% off", authors: ["success"] },
              { label: "B", text: "10% off", authors: ["finance"] },
            ],
            table: { A: { success: 95, finance: 30 }, B: { success: 55, finance: 90 } },
            cast: ["success", "finance", "legal"],
            ratings: { success: 55, finance: 90 },
            lowest: 55,
            missing: ["legal"],
            least_happy: "success",
          },
        }}
        text="| option | …"
      />,
    );
    const table = screen.getByRole("table", { name: "Ratings, bar 70" });
    const rows = table.querySelectorAll("tbody tr");
    expect(rows[1].textContent).toBe("B 10% off5590?");
    expect(screen.getByTestId("conductor-row").textContent).toContain("B, @success at 55; no rating from @legal");
  });

  it("draws an agreement as a success that says what it went with", () => {
    render(
      <ConductorRow
        line={{
          event: "close",
          protocol: "concord",
          outcome: "converged",
          steps: 4,
          reason: "reached `agreed`",
          pick: "C",
          text: "15% off for two years",
        }}
        text="✓ Everyone's on board: going with C"
      />,
    );
    const row = screen.getByTestId("conductor-row").textContent;
    expect(row).toContain("✓ Everyone's on board: going with C");
    expect(row).toContain("15% off for two years");
  });

  it("draws a count of points and of words as one plain line", () => {
    const { rerender } = render(
      <ConductorRow
        line={{
          event: "tally",
          step: "added",
          next: "ground",
          tally: { of: "points", round: 2, max_rounds: 3, outcome: "settled", added: 0, points: 5, capped: false },
        }}
        text="Nobody added anything new."
      />,
    );
    expect(screen.getByTestId("conductor-row").textContent).toBe("added: Nobody added anything new: 5 points");
    expect(screen.queryByRole("button")).toBeNull();

    rerender(
      <ConductorRow
        line={{
          event: "tally",
          step: "words",
          next: "restate",
          tally: {
            of: "terms",
            round: 1,
            max_rounds: 2,
            outcome: "contested",
            words: 2,
            contested: ["renewal"],
            asked: ["a", "b"],
          },
        }}
        text="…"
      />,
    );
    expect(screen.getByTestId("conductor-row").textContent).toContain(
      "Words used in different senses: renewal. Asking a, b again",
    );
  });

  const lock = {
    outcome: "locked" as const,
    memory: "context/summary/acme-renewal",
    saved: true,
    points: 5,
    shared: 1,
    contested: 0,
    checks: 1,
    flagged: 4,
    quiet: [],
  };

  it("draws the shared summary with a link that opens the memory it was saved to", () => {
    const opened: string[] = [];
    render(
      <ConductorRow
        line={{ event: "lock", step: "lock", next: "locked", lock }}
        text="…"
        onOpenMemory={(key) => opened.push(key)}
      />,
    );
    const row = screen.getByTestId("conductor-row").textContent;
    expect(row).toContain("Shared summary: 5 points, 1 stated by more than one person, 1 check, 4 open items");
    fireEvent.click(screen.getByRole("button", { name: "context/summary/acme-renewal" }));
    expect(opened).toEqual(["context/summary/acme-renewal"]);
  });

  it("says a shared summary that could not be saved, and draws an empty one without a link", () => {
    const { rerender } = render(
      <ConductorRow line={{ event: "lock", step: "lock", next: "locked", lock: { ...lock, memory: null, saved: false } }} text="…" />,
    );
    expect(screen.getByTestId("conductor-row").textContent).toContain("could not be saved");

    rerender(
      <ConductorRow
        line={{ event: "lock", step: "lock", next: "nothing", lock: { ...lock, outcome: "empty", memory: null, saved: false, points: 0 } }}
        text="…"
      />,
    );
    expect(screen.getByTestId("conductor-row").textContent).toBe("Nothing to put in a shared summary");
  });

  it("links the end of a run to what it saved, or says it could not be saved", () => {
    const close = { event: "close" as const, protocol: "accord", outcome: "resolved", steps: 4, reason: "reached `locked`" };
    const opened: string[] = [];
    const { rerender } = render(
      <ConductorRow line={{ ...close, memory: "context/summary/acme-renewal" }} text="✓" onOpenMemory={(k) => opened.push(k)} />,
    );
    expect(screen.getByTestId("conductor-row").textContent).toContain("accord done");
    fireEvent.click(screen.getByRole("button", { name: "context/summary/acme-renewal" }));
    expect(opened).toEqual(["context/summary/acme-renewal"]);

    rerender(<ConductorRow line={{ ...close, memory: null }} text="✓" />);
    expect(screen.getByTestId("conductor-row").textContent).toContain("could not be saved");

    // A run from before anything was saved carries no memory, and says nothing about one.
    rerender(<ConductorRow line={close} text="✓" />);
    expect(screen.getByTestId("conductor-row").textContent).not.toContain("saved");
  });
});
