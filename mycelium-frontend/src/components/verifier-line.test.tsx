// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { VerifierFlag } from "@/lib/api";

const markVerifierFlagFine = vi.fn().mockResolvedValue({});

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  markVerifierFlagFine: (...args: unknown[]) => markVerifierFlagFine(...args),
}));
vi.mock("@/components/current-user", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/current-user")>()),
  useCurrentUser: () => ({ principal: "julia" }),
}));

import { VerifierLines } from "@/components/verifier-line";
import { MessageBody } from "@/components/message-body";

const FLAG: VerifierFlag = {
  flag_id: "vf1",
  failure: "ungranted_approval",
  message_id: "h4",
  key: "live",
  about: "builder",
  by: "verifier",
  claim: "approval",
  ref: "#502",
  line: "Can't find an approval for #502.",
  sure: false,
  quotes: ["#502 is approved and green"],
  sentence: "#502 is approved and green, so it can go to staging.",
  why: "Nobody in this room has approved #502.",
  checked: [{ what: "Approvals of #502 in this room", found: "none" }],
  state: "shown",
  at: "2026-10-13T12:00:00Z",
};

beforeEach(() => markVerifierFlagFine.mockClear());

describe("<VerifierLines />", () => {
  it("shows the verifier's own line, soft when nothing was found and darker when the records disagree", () => {
    const { rerender } = render(<VerifierLines roomName="checkout" flags={[FLAG]} />);
    expect(screen.getByText("Can't find an approval for #502.")).not.toHaveClass("font-medium");
    rerender(<VerifierLines roomName="checkout" flags={[{ ...FLAG, sure: true, line: "#502 was already merged, at 20:08." }]} />);
    expect(screen.getByText("#502 was already merged, at 20:08.")).toHaveClass("font-medium");
  });

  it("names the failure and lists what it read under Show why", async () => {
    render(<VerifierLines roomName="checkout" flags={[FLAG]} />);
    await userEvent.click(screen.getByRole("button", { name: "Show why" }));
    expect(await screen.findByText("Approval nobody gave")).toBeInTheDocument();
    expect(screen.getByText("Approvals of #502 in this room")).toBeInTheDocument();
    expect(screen.getByText("Nobody in this room has approved #502.")).toBeInTheDocument();
  });

  it("dismisses it as the person acting, and takes the line away", async () => {
    const onChanged = vi.fn();
    render(<VerifierLines roomName="checkout" flags={[FLAG]} onChanged={onChanged} />);
    await userEvent.click(screen.getByRole("button", { name: "It's fine" }));
    await waitFor(() => expect(markVerifierFlagFine).toHaveBeenCalledWith("checkout", "vf1", "julia"));
    expect(onChanged).toHaveBeenCalled();
    expect(screen.queryByText("Can't find an approval for #502.")).toBeNull();
  });
});

describe("<MessageBody claims />", () => {
  it("underlines the claimed words, and a find hit draws instead while one is open", () => {
    const content = "apple pay works. #502 is approved and green, so ship it.";
    const { container, rerender } = render(<MessageBody content={content} claims={["#502 is approved and green"]} />);
    expect(container.querySelector("mark[data-claim]")?.textContent).toBe("#502 is approved and green");
    rerender(<MessageBody content={content} claims={["#502 is approved and green"]} hit={{ query: "apple" }} />);
    expect(container.querySelector("mark[data-claim]")).toBeNull();
    expect(container.querySelector("mark[data-find-match]")?.textContent).toBe("apple");
  });
});
