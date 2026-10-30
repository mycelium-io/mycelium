// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// An agent's ask for one person's OK: only that person can answer it, an
// answer goes to the hub as a decision (and a reason, on a decline), and once
// answered the card is the record of who decided and why.

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithSWR } from "@/test/swr";
import type { ApprovalAsk } from "@/lib/approvals";

const answerAsk = vi.fn().mockResolvedValue({});
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  answerAsk: (...args: unknown[]) => answerAsk(...args),
}));

let principal = "operator";
vi.mock("@/components/current-user", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/current-user")>()),
  useCurrentUser: () => ({ principal }),
}));
vi.mock("@/lib/people", () => ({
  useNames: () => new Map([["operator", "Morgan Reyes"]]),
  nameOf: (names: Map<string, string>, handle: string) => names.get(handle),
}));

import { ApprovalCard } from "@/components/approval-card";

const ask = (over: Partial<ApprovalAsk> = {}): ApprovalAsk => ({
  id: "7e21c0a4",
  kind: "approve",
  to: "operator",
  question: "Turn Apple Pay on for everyone on Friday at 9:00",
  happens: "The switch turns on for every customer.",
  why: null,
  undo: "Turn the switch off.",
  link: null,
  answer: null,
  ...over,
});

beforeEach(() => {
  principal = "operator";
  answerAsk.mockClear();
});

describe("an approval card", () => {
  it("shows the question and only the facts the agent gave", () => {
    renderWithSWR(<ApprovalCard roomName="checkout" ask={ask()} />);
    expect(screen.getByText("Turn Apple Pay on for everyone on Friday at 9:00")).toBeInTheDocument();
    expect(screen.getByText("What happens")).toBeInTheDocument();
    expect(screen.getByText("To undo")).toBeInTheDocument();
    expect(screen.queryByText("Why now")).toBeNull();
    expect(screen.getByText("asks Morgan Reyes")).toBeInTheDocument();
  });

  it("approves as the person asked, and then reads as the record", async () => {
    renderWithSWR(<ApprovalCard roomName="checkout" ask={ask()} />);
    await userEvent.click(screen.getByRole("button", { name: /Approve/ }));
    expect(answerAsk).toHaveBeenCalledWith("checkout", "7e21c0a4", { decision: "approved", reason: null, by: "operator" });
    expect(await screen.findByText(/Approved by Morgan Reyes/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Approve/ })).toBeNull();
  });

  it("declines with a reason, in place", async () => {
    renderWithSWR(<ApprovalCard roomName="checkout" ask={ask()} />);
    await userEvent.click(screen.getByRole("button", { name: "Decline…" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Why not" }), "Wait until the sale is over{Enter}");
    expect(answerAsk).toHaveBeenCalledWith("checkout", "7e21c0a4", {
      decision: "declined",
      reason: "Wait until the sale is over",
      by: "operator",
    });
    expect(await screen.findByText(/Declined by Morgan Reyes/)).toBeInTheDocument();
    expect(screen.getByText("“Wait until the sale is over”")).toBeInTheDocument();
  });

  it("gives anyone else no buttons, only whom it waits on", () => {
    principal = "jamie";
    renderWithSWR(<ApprovalCard roomName="checkout" ask={ask()} />);
    expect(screen.getByText("Waiting on Morgan Reyes")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Approve/ })).toBeNull();
  });

  it("says it needs your OK only to the person asked, and only until they answer", () => {
    renderWithSWR(<ApprovalCard roomName="checkout" ask={ask()} />);
    expect(screen.getByText("Needs your OK")).toBeInTheDocument();
  });

  it.each([
    ["someone else", "jamie", null],
    ["the person asked, once answered", "operator", { decision: "approved" as const, reason: null, by: "operator", at: "" }],
  ])("reads as an approval to %s", (_who, me, answer) => {
    principal = me;
    renderWithSWR(<ApprovalCard roomName="checkout" ask={ask({ answer })} />);
    expect(screen.getByText("Approval")).toBeInTheDocument();
    expect(screen.queryByText("Needs your OK")).toBeNull();
  });

  it("opens a linked page in a new tab, a linked memory in the room, and shows anything else as written", async () => {
    const onOpenMemory = vi.fn();
    const { rerender } = renderWithSWR(
      <ApprovalCard roomName="checkout" ask={ask({ link: "https://github.com/acme/shop/pull/504" })} onOpenMemory={onOpenMemory} />,
    );
    expect(screen.getByRole("link", { name: /pull\/504/ })).toHaveAttribute("target", "_blank");

    rerender(<ApprovalCard roomName="checkout" ask={ask({ link: "decisions/apple-pay-launch" })} onOpenMemory={onOpenMemory} />);
    await userEvent.click(screen.getByRole("button", { name: /decisions\/apple-pay-launch/ }));
    expect(onOpenMemory).toHaveBeenCalledWith("decisions/apple-pay-launch");

    rerender(<ApprovalCard roomName="checkout" ask={ask({ link: "the staging build" })} onOpenMemory={onOpenMemory} />);
    expect(screen.getByText("the staging build")).toBeInTheDocument();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("draws an answered ask as the record, for everyone", () => {
    principal = "jamie";
    renderWithSWR(
      <ApprovalCard
        roomName="checkout"
        ask={ask({ answer: { decision: "declined", reason: "Not before the sale", by: "operator", at: "2026-10-30T10:42:00Z" } })}
      />,
    );
    expect(screen.getByText(/Declined by Morgan Reyes/)).toBeInTheDocument();
    expect(screen.getByText("“Not before the sale”")).toBeInTheDocument();
    expect(screen.queryByText(/Waiting on/)).toBeNull();
  });

  it("says so when the hub refuses the answer", async () => {
    answerAsk.mockRejectedValueOnce(new Error("This ask has been answered."));
    renderWithSWR(<ApprovalCard roomName="checkout" ask={ask()} />);
    await userEvent.click(screen.getByRole("button", { name: /Approve/ }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("This ask has been answered."));
    expect(screen.getByRole("button", { name: /Approve/ })).toBeInTheDocument();
  });
});
