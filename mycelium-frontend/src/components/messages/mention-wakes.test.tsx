// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const interruptMention = vi.fn();
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  interruptMention: (...args: unknown[]) => interruptMention(...args),
}));

import { InterruptMark, SentToWorking } from "@/components/messages/mention-wakes";

beforeEach(() => {
  interruptMention.mockReset().mockResolvedValue({ by: "operator", handle: "builder", at: "" });
});

describe("<SentToWorking />", () => {
  it("says the member is working and interrupts it with the message just sent", async () => {
    const onDone = vi.fn();
    render(<SentToWorking roomName="checkout" messageId="m-1" handles={["builder"]} me="operator" onDone={onDone} />);
    expect(screen.getByText(/^is working\.$/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Interrupt/ }));
    expect(interruptMention).toHaveBeenCalledWith("checkout", "m-1", "builder", "operator");
    expect(await screen.findByText(/Interrupted @builder/)).toBeInTheDocument();
  });

  it("says why when the hub refuses", async () => {
    interruptMention.mockRejectedValueOnce(new Error("@builder has m-1 already"));
    render(<SentToWorking roomName="checkout" messageId="m-1" handles={["builder"]} me="operator" onDone={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: /Interrupt/ }));
    expect(await screen.findByText("@builder has m-1 already")).toBeInTheDocument();
  });
});

describe("<InterruptMark />", () => {
  it("marks a message with who its sender interrupted, and nothing when nobody", () => {
    const { rerender } = render(
      <InterruptMark marks={[{ by: "operator", handle: "builder", at: "2026-11-06T10:00:00Z" }]} />,
    );
    expect(screen.getByRole("img", { name: "Interrupted @builder" })).toBeInTheDocument();
    rerender(<InterruptMark marks={[]} />);
    expect(screen.queryByRole("img")).toBeNull();
  });
});
