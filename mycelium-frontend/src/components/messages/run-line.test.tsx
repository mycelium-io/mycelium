import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ConductorLine, RunProgress } from "@/lib/conductor-line";
import { RunStartLine } from "./run-line";

const open = {
  event: "open",
  protocol: "fan-out",
  roles: {},
  members: ["builder", "reviewer", "designer"],
  steps: [],
} as Extract<ConductorLine, { event: "open" }>;

const progress = (over: Partial<RunProgress>): RunProgress => ({
  protocol: "fan-out",
  members: open.members,
  open: true,
  doing: null,
  ...over,
});

describe("a conductor run in the channel", () => {
  it("starts as one line that names the step being asked, live", () => {
    const onOpen = vi.fn();
    const { rerender } = render(
      <RunStartLine
        time="10:00"
        open={open}
        progress={progress({ doing: { what: "gather", asked: 3, answered: 2 } })}
        title="Make the shares add up"
        onOpen={onOpen}
      />,
    );
    expect(screen.getByText("Fan-out started")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("gather, 2 of 3 in");
    fireEvent.click(screen.getByRole("button", { name: /Make the shares add up/ }));
    expect(onOpen).toHaveBeenCalled();

    rerender(<RunStartLine time="10:00" open={open} progress={progress({ open: false })} title="Make the shares add up" />);
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.getByText("builder, reviewer, designer")).toBeInTheDocument();
  });
});
