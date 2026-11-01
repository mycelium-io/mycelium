import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import type { ConductorLine, PickRecord } from "@/lib/conductor-line";

let thread: { content: string; metadata: unknown }[] = [];
vi.mock("@/lib/room-data", () => ({
  // Newest first, as the hub answers.
  useThreadMessages: () => ({ messages: [...thread].reverse() }),
}));

import { RunResult, closedRun } from "./run-result";
import { ReplyValues } from "./reply-values";

const pick: PickRecord = {
  outcome: "feasible",
  pick: "A",
  text: "In tipcalc.py, compute the bill with tip as total * (1 + tip_percent/100).",
  threshold: 60,
  options: [
    { label: "A", text: "In tipcalc.py, compute the bill with tip as total * (1 + tip_percent/100).", authors: ["builder"] },
    { label: "B", text: "Change split() to work in whole cents.", authors: ["reviewer"] },
  ],
  table: { A: { builder: 90, reviewer: 80, designer: 75 }, B: { builder: 85, reviewer: 45, designer: 55 } },
  placed: { A: { builder: 1, reviewer: 0.88, designer: 0.81 }, B: { builder: 0.94, reviewer: 0.44, designer: 0.56 } },
  reasons: {
    A: { builder: "my pick", reviewer: "right math", designer: "format left open" },
    B: { reviewer: "no sum test", designer: "no total line" },
  },
  cast: ["builder", "reviewer", "designer"],
  ratings: { builder: 90, reviewer: 80, designer: 75 },
  lowest: 0.81,
  missing: [],
  least_happy: null,
};

const line = (conductor: ConductorLine) => ({ content: "…", metadata: { conductor } });
const open = line({ event: "open", protocol: "concord", roles: {}, members: ["builder"], steps: [] });
const select = line({ event: "select", step: "pick", next: "agreed", select: pick });
const close = line({
  event: "close",
  protocol: "concord",
  outcome: "converged",
  steps: 3,
  reason: "reached `agreed`",
  pick: "A",
  text: pick.text,
  memory: "context/decision/make-the-shares-add-up-to-the-bill",
});

describe("RunResult", () => {
  it("leads a closed Concord run with the pick, how satisfied each member is, and the decision", () => {
    thread = [open, select, close];
    const onOpen = vi.fn();
    render(<RunResult roomName="r" episode="e" onOpenMemory={onOpen} />);
    const result = screen.getByRole("region", { name: "Result" });
    expect(within(result).getByRole("heading")).toHaveTextContent("Picked A");
    // The options once, by letter, the whole text a click away.
    const options = within(within(result).getByRole("list", { name: "Options" })).getAllByRole("button");
    expect(options.map((o) => o.textContent)).toEqual([`A${pick.options[0].text}`, `B${pick.options[1].text}`]);
    fireEvent.click(options[1]);
    expect(options[1]).toHaveAttribute("aria-expanded", "true");
    const bars = within(result).getByRole("list", { name: "How satisfied each member is with the pick" });
    expect(within(bars).getAllByRole("meter").map((m) => m.getAttribute("aria-valuenow"))).toEqual(["100", "88", "81"]);
    // Each bar ends in its number, and the line is named once.
    expect(within(bars).getAllByRole("listitem").map((r) => r.textContent)).toEqual([
      "builder100%my pick",
      "reviewer88%right math",
      "designer81%format left open",
    ]);
    expect(bars).toHaveTextContent("bar 60%");
    expect(result).toHaveTextContent("designer is least satisfied, at 81% of the way to their ideal");
    expect(result).not.toHaveTextContent("meets the bar");
    fireEvent.click(within(result).getByRole("button", { name: "Open decision" }));
    expect(onOpen).toHaveBeenCalledWith("context/decision/make-the-shares-add-up-to-the-bill");
  });

  it("says a run that missed the bar is the best found", () => {
    thread = [open, select, line({ event: "close", protocol: "concord", outcome: "resolved", steps: 9, reason: "", pick: "A", text: pick.text })];
    render(<RunResult roomName="r" episode="e" />);
    expect(screen.getByRole("heading")).toHaveTextContent("Best found: A");
  });

  it("leads a closed Accord run with its shared summary and how much is open", () => {
    thread = [
      line({
        event: "lock",
        step: "lock",
        next: "locked",
        lock: {
          outcome: "locked",
          memory: "context/summary/handle-bad-input",
          saved: true,
          points: 17,
          shared: 2,
          contested: 1,
          checks: 13,
          flagged: 4,
          quiet: [],
        },
      }),
      line({ event: "close", protocol: "accord", outcome: "resolved", steps: 5, reason: "reached `locked`", memory: "context/summary/handle-bad-input" }),
    ];
    render(<RunResult roomName="r" episode="e" onOpenMemory={vi.fn()} />);
    const result = screen.getByRole("region", { name: "Result" });
    expect(result).toHaveTextContent("Shared summary 17 points, 4 open");
    expect(within(result).getByRole("button", { name: "Open summary" })).toBeInTheDocument();
  });

  it("draws nothing while a run is still going", () => {
    thread = [open, select];
    const { container } = render(<RunResult roomName="r" episode="e" />);
    expect(container).toBeEmptyDOMElement();
    // A run opened after one closed is going again.
    expect(closedRun([open, select, close, open].map((m) => m.metadata.conductor as ConductorLine))).toBeNull();
  });
});

describe("ReplyValues", () => {
  it("draws a rating reply's options as bars by letter, from the pick that read it", () => {
    render(<ReplyValues context={{ rated: { record: pick, member: "reviewer" } }} />);
    const bars = screen.getByRole("list", { name: "How close each option gets them to their ideal" });
    const rows = within(bars).getAllByRole("listitem");
    expect(rows.map((r) => r.textContent)).toEqual(["A88%right math", "B44%no sum test"]);
    // B is short of the bar for reviewer.
    expect((within(rows[1]).getByRole("meter").firstChild as HTMLElement).style.background).toBe("var(--yellow)");
  });

  it("draws nothing for a reply no pick read", () => {
    const { container } = render(<ReplyValues />);
    expect(container).toBeEmptyDOMElement();
  });
});
