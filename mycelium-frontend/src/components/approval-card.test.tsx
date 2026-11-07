// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// An agent's ask: put to one person, answerable by anyone in the room, with a
// note on every kind. Approve sends a decision, choose the options picked, a
// question its text. Once answered it folds to the question with what was
// decided under it, and opens to the whole record.

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithSWR } from "@/test/swr";
import type { ApprovalAsk, AskAnswer } from "@/lib/approvals";

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
  useNames: () => new Map([["operator", "Morgan Reyes"], ["jamie", "Jamie Park"]]),
  nameOf: (names: Map<string, string>, handle: string) => names.get(handle),
}));

import { AskCard } from "@/components/approval-card";

const base = {
  id: "7e21c0a4",
  to: "operator",
  happens: null,
  why: null,
  undo: null,
  link: null,
  options: [],
  multiple: false,
  recommend: [],
  recommendsApprove: false,
  suggest: null,
  answer: null,
};
const approve = (over: Partial<ApprovalAsk> = {}): ApprovalAsk => ({
  ...base,
  kind: "approve",
  question: "Turn Apple Pay on Friday?",
  happens: "The switch turns on for every customer.",
  undo: "Turn the switch off.",
  ...over,
});
const choose = (over: Partial<ApprovalAsk> = {}): ApprovalAsk => ({
  ...base,
  kind: "choose",
  question: "Which payment provider first?",
  options: [
    { id: "1", label: "Stripe", detail: null },
    { id: "2", label: "Adyen", detail: "Needs a new contract." },
    { id: "3", label: "Wait a week", detail: null },
  ],
  recommend: ["1"],
  ...over,
});
const question = (over: Partial<ApprovalAsk> = {}): ApprovalAsk => ({
  ...base,
  kind: "question",
  question: "What's slowest at checkout?",
  ...over,
});
const answered = (over: Partial<AskAnswer>): AskAnswer => ({
  kind: "approve",
  question: "Turn Apple Pay on Friday?",
  for: "operator",
  by: "operator",
  at: "2026-10-30T10:42:00Z",
  decision: "approved",
  choices: [],
  chosen: [],
  text: null,
  ...over,
});

beforeEach(() => {
  principal = "operator";
  answerAsk.mockClear();
});

describe("an approve", () => {
  it("shows the question and only the facts the agent gave, as the asked person's", () => {
    renderWithSWR(<AskCard roomName="checkout" ask={approve()} />);
    expect(screen.getByText("Needs your OK")).toBeInTheDocument();
    expect(screen.getByText("Turn Apple Pay on Friday?")).toBeInTheDocument();
    expect(screen.getByText("What happens")).toBeInTheDocument();
    expect(screen.queryByText("Why now")).toBeNull();
  });

  it("approves with the note typed beside it", async () => {
    renderWithSWR(<AskCard roomName="checkout" ask={approve()} />);
    await userEvent.type(screen.getByRole("textbox", { name: "Note" }), "Ship it after the iPhone test");
    await userEvent.click(screen.getByRole("button", { name: /Approve/ }));
    expect(answerAsk).toHaveBeenCalledWith("checkout", "7e21c0a4", {
      by: "operator",
      decision: "approved",
      text: "Ship it after the iPhone test",
    });
    expect(await screen.findByRole("button", { expanded: false })).toHaveTextContent("Approved · “Ship it after the iPhone test”");
  });

  it("declines, with no note needed", async () => {
    renderWithSWR(<AskCard roomName="checkout" ask={approve()} />);
    await userEvent.click(screen.getByRole("button", { name: "Decline" }));
    expect(answerAsk).toHaveBeenCalledWith("checkout", "7e21c0a4", { by: "operator", decision: "declined" });
  });

  it("says when the agent recommends going ahead", () => {
    renderWithSWR(<AskCard roomName="checkout" ask={approve({ recommendsApprove: true })} />);
    expect(screen.getByText("recommended")).toBeInTheDocument();
  });
});

describe("a choose", () => {
  it("starts on the agent's pick, and sends the one picked", async () => {
    renderWithSWR(<AskCard roomName="checkout" ask={choose()} />);
    expect(screen.getByText("Pick one")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Stripe/ })).toBeChecked();
    await userEvent.click(screen.getByRole("radio", { name: /Adyen/ }));
    expect(screen.getByRole("radio", { name: /Stripe/ })).not.toBeChecked();
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(answerAsk).toHaveBeenCalledWith("checkout", "7e21c0a4", { by: "operator", choices: ["2"] });
  });

  it("takes several when it says so, and counts them on the button", async () => {
    renderWithSWR(<AskCard roomName="checkout" ask={choose({ multiple: true, recommend: ["1", "3"] })} />);
    expect(screen.getByText("Pick any")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("checkbox", { name: /Adyen/ }));
    await userEvent.click(screen.getByRole("button", { name: "Send 3" }));
    expect(answerAsk).toHaveBeenCalledWith("checkout", "7e21c0a4", { by: "operator", choices: ["1", "2", "3"] });
  });

  it.each([
    ["one", false],
    ["several", true],
  ])("can be answered with none of its options when it takes %s, with a note", async (_takes, multiple) => {
    // The agent's pick is ticked; None of these still sends none.
    renderWithSWR(<AskCard roomName="checkout" ask={choose({ multiple })} />);
    await userEvent.type(screen.getByRole("textbox", { name: "Note" }), "neither fits our contract");
    await userEvent.click(screen.getByRole("button", { name: "None of these" }));
    expect(answerAsk).toHaveBeenCalledWith("checkout", "7e21c0a4", {
      by: "operator",
      choices: [],
      text: "neither fits our contract",
    });
    // It folds to the question, with what was answered under it.
    expect(await screen.findByText(/^Chose none of the options/)).toHaveTextContent("neither fits our contract");
  });

  it("won't send with nothing ticked: none is its own button", async () => {
    renderWithSWR(<AskCard roomName="checkout" ask={choose({ multiple: true, recommend: [] })} />);
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "None of these" })).toBeEnabled();
  });
});

describe("a question", () => {
  it("starts from the agent's draft, and sends the text", async () => {
    renderWithSWR(<AskCard roomName="checkout" ask={question({ suggest: "The address form." })} />);
    const box = screen.getByRole("textbox", { name: "Your answer" });
    expect(box).toHaveValue("The address form.");
    await userEvent.type(box, " It reloads on every typo.");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(answerAsk).toHaveBeenCalledWith("checkout", "7e21c0a4", {
      by: "operator",
      text: "The address form. It reloads on every typo.",
    });
  });

  it("won't send an empty answer", () => {
    renderWithSWR(<AskCard roomName="checkout" ask={question()} />);
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  });
});

describe("skipping", () => {
  it.each([
    ["an approve", approve],
    ["a choose", choose],
  ])("skips %s with its note, and sends no answer of its own", async (_kind, make) => {
    renderWithSWR(<AskCard roomName="checkout" ask={make()} />);
    await userEvent.type(screen.getByRole("textbox", { name: "Note" }), "not mine to call");
    await userEvent.click(screen.getByRole("button", { name: "Skip" }));
    expect(answerAsk).toHaveBeenCalledWith("checkout", "7e21c0a4", {
      by: "operator",
      skipped: true,
      text: "not mine to call",
    });
    expect(await screen.findByText(/^Skipped/)).toHaveTextContent("not mine to call");
  });

  it("skips a question without sending its text box as a note", async () => {
    renderWithSWR(<AskCard roomName="checkout" ask={question({ suggest: "The address form." })} />);
    await userEvent.click(screen.getByRole("button", { name: "Skip" }));
    expect(answerAsk).toHaveBeenCalledWith("checkout", "7e21c0a4", { by: "operator", skipped: true });
    expect(await screen.findByText(/^Skipped/)).toBeInTheDocument();
  });
});

describe("anyone else in the room", () => {
  it("sees whom it asks, and can answer it for them", async () => {
    principal = "jamie";
    renderWithSWR(<AskCard roomName="checkout" ask={approve()} />);
    expect(screen.getByText("Asks Morgan Reyes")).toBeInTheDocument();
    expect(screen.queryByText("Needs your OK")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /Approve/ }));
    expect(answerAsk).toHaveBeenCalledWith("checkout", "7e21c0a4", { by: "jamie", decision: "approved" });
  });
});

describe("an answered ask", () => {
  it("folds to the question, with what was decided under it, the note, who and for whom", async () => {
    principal = "operator";
    const ask = choose({ answer: answered({ kind: "choose", decision: null, choices: ["1"], chosen: ["Stripe"], by: "jamie", text: "revisit in spring" }) });
    renderWithSWR(<AskCard roomName="checkout" ask={ask} />);
    const line = screen.getByRole("button", { expanded: false });
    const text = line.textContent ?? "";
    expect(text.indexOf("Which payment provider first?")).toBeLessThan(text.indexOf("Chose Stripe"));
    expect(line).toHaveTextContent("Chose Stripe");
    expect(line).toHaveTextContent("revisit in spring");
    expect(line).toHaveTextContent("Jamie Park for you");
    expect(screen.queryByRole("radio")).toBeNull();

    await userEvent.click(line);
    expect(screen.getByRole("radio", { name: /Stripe/ })).toBeChecked();
    expect(screen.getByRole("radio", { name: /Stripe/ })).toBeDisabled();
    expect(screen.getByText("“revisit in spring”")).toBeInTheDocument();
  });

  it("reads a declined approve as declined", () => {
    renderWithSWR(<AskCard roomName="checkout" ask={approve({ answer: answered({ decision: "declined", text: "wait for CI" }) })} />);
    expect(screen.getByRole("button", { expanded: false })).toHaveTextContent("Declined");
  });
});

it("says so when the hub refuses the answer, and keeps the card open", async () => {
  answerAsk.mockRejectedValueOnce(new Error("Already approved by @jamie"));
  renderWithSWR(<AskCard roomName="checkout" ask={approve()} />);
  await userEvent.click(screen.getByRole("button", { name: /Approve/ }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Already approved by @jamie"));
  expect(screen.getByRole("button", { name: /Approve/ })).toBeInTheDocument();
});

it("opens a linked memory in the room", async () => {
  const onOpenMemory = vi.fn();
  renderWithSWR(<AskCard roomName="checkout" ask={approve({ link: "decisions/apple-pay-launch" })} onOpenMemory={onOpenMemory} />);
  await userEvent.click(screen.getByRole("button", { name: /decisions\/apple-pay-launch/ }));
  expect(onOpenMemory).toHaveBeenCalledWith("decisions/apple-pay-launch");
});
