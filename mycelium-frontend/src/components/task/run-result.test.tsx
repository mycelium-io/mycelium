import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import type { ConductorLine } from "@/lib/conductor-line";

let thread: { content: string; metadata: unknown }[] = [];
vi.mock("@/lib/room-data", () => ({
  // Newest first, as the hub answers.
  useThreadMessages: () => ({ messages: [...thread].reverse() }),
}));

import { RunResult, closedRun } from "./run-result";

const line = (conductor: ConductorLine) => ({ content: "…", metadata: { conductor } });
const open = line({ event: "open", protocol: "review", roles: { author: "builder", reviewer: "reviewer" }, members: [], steps: [] });
const turn = line({ event: "turn", protocol: "review", step: "build", to: "builder", turn: 1, cap: 12 });
const close = line({ event: "close", protocol: "review", outcome: "resolved", steps: 3, reason: "reached `passed`" });

describe("RunResult", () => {
  it("leads a closed run with how it ended", () => {
    thread = [open, turn, close];
    render(<RunResult roomName="r" episode="e" />);
    const result = screen.getByRole("region", { name: "Result" });
    expect(within(result).getByRole("heading")).toHaveTextContent("review done");
    expect(within(result).getByLabelText("succeeded")).toBeInTheDocument();
  });

  it("says a rejected run ended short", () => {
    thread = [open, turn, line({ event: "close", protocol: "review", outcome: "rejected", steps: 9, reason: "" })];
    render(<RunResult roomName="r" episode="e" />);
    expect(screen.getByRole("heading")).toHaveTextContent("review rejected");
    expect(screen.getByLabelText("ended short")).toBeInTheDocument();
  });

  it("draws nothing while a run is still going", () => {
    thread = [open, turn];
    const { container } = render(<RunResult roomName="r" episode="e" />);
    expect(container).toBeEmptyDOMElement();
    // A run opened after one closed is going again.
    expect(closedRun([open, turn, close, open].map((m) => m.metadata.conductor as ConductorLine))).toBeNull();
  });
});
