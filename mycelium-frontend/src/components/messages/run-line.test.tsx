import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ConductorLine, PickRecord, RunProgress } from "@/lib/conductor-line";
import { RunDoneLine, RunStartLine } from "./run-line";

const open = {
  event: "open",
  protocol: "concord",
  roles: {},
  members: ["builder", "reviewer", "designer"],
  steps: [],
} as Extract<ConductorLine, { event: "open" }>;

const progress = (over: Partial<RunProgress>): RunProgress => ({
  protocol: "concord",
  members: open.members,
  open: true,
  doing: null,
  lock: null,
  ...over,
});

describe("a conductor run in the channel", () => {
  it("starts as one line that says what the members are doing, live", () => {
    const onOpen = vi.fn();
    const { rerender } = render(
      <RunStartLine
        time="10:00"
        open={open}
        progress={progress({ doing: { what: "scoring", asked: 3, answered: 2 } })}
        title="Make the shares add up"
        onOpen={onOpen}
      />,
    );
    expect(screen.getByText("Concord started")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("scoring, 2 of 3 in");
    fireEvent.click(screen.getByRole("button", { name: /Make the shares add up/ }));
    expect(onOpen).toHaveBeenCalled();

    rerender(<RunStartLine time="10:00" open={open} progress={progress({ open: false })} title="Make the shares add up" />);
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.getByText("builder, reviewer, designer")).toBeInTheDocument();
  });

  it("ends saying what Concord picked and who is least satisfied, the option's text on hover", () => {
    const pick = {
      pick: "C",
      cast: ["builder", "reviewer", "designer"],
      table: { C: { builder: 88, reviewer: 85, designer: 96 } },
      placed: { C: { builder: 0.88, reviewer: 0.85, designer: 0.96 } },
      options: [{ label: "C", text: "Fix the tip math and print each share.", authors: ["designer"] }],
    } as unknown as PickRecord;
    const close = {
      event: "close",
      protocol: "concord",
      outcome: "converged",
      steps: 4,
      reason: "",
      pick: "C",
      text: "Fix the tip math and print each share.",
    } as const;
    const { rerender } = render(
      <RunDoneLine time="10:05" close={close} pick={pick} progress={progress({ open: false })} title="Make the shares add up" />,
    );
    expect(screen.getByText("Concord ended")).toBeInTheDocument();
    const detail = screen.getByTitle("Fix the tip math and print each share.");
    expect(detail).toHaveTextContent(/^picked C, reviewer least satisfied at 85%$/);

    // Short of the bar when the fixes ran out: the best found.
    rerender(
      <RunDoneLine
        time="10:05"
        close={{ ...close, outcome: "resolved" }}
        pick={pick}
        progress={progress({ open: false })}
        title="Make the shares add up"
      />,
    );
    expect(screen.getByTitle("Fix the tip math and print each share.")).toHaveTextContent(/^best found C/);
  });

  it("ends saying what Accord locked and how much is open", () => {
    render(
      <RunDoneLine
        time="10:05"
        close={{
          event: "close",
          protocol: "accord",
          outcome: "resolved",
          steps: 7,
          reason: "",
          memory: "context/summary/handle-bad-input",
        }}
        pick={null}
        progress={progress({
          protocol: "accord",
          open: false,
          lock: { outcome: "locked", memory: "m", saved: true, points: 17, shared: 0, contested: 2, checks: 2, flagged: 2, quiet: [] },
        })}
        title="Handle bad input"
      />,
    );
    expect(screen.getByText("Accord ended")).toBeInTheDocument();
    expect(screen.getByText(/summary locked/)).toHaveTextContent(/^summary locked, 17 points, 2 open$/);
  });
});
