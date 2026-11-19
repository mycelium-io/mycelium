// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const reactToMessage = vi.fn().mockResolvedValue({ reactions: [] });

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  reactToMessage: (...args: unknown[]) => reactToMessage(...args),
}));
vi.mock("@/components/current-user", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/current-user")>()),
  useCurrentUser: () => ({ principal: "julia" }),
}));

import { ReactionChips, whoReacted } from "@/components/messages/reactions";

describe("<ReactionChips />", () => {
  beforeEach(() => reactToMessage.mockClear());

  it("draws nothing for a message with no reactions", () => {
    const { container } = render(<ReactionChips roomName="checkout" messageId="m1" reactions={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows each emoji with its count, and marks the ones you put on", () => {
    render(
      <ReactionChips
        roomName="checkout"
        messageId="m1"
        reactions={[
          { emoji: "🎉", by: ["lead", "julia"] },
          { emoji: "👀", by: ["lead"] },
        ]}
      />,
    );
    const party = screen.getByRole("button", { name: "🎉 from @lead and you" });
    expect(party).toHaveAttribute("aria-pressed", "true");
    expect(party).toHaveTextContent("2");
    expect(screen.getByRole("button", { name: "👀 from @lead" })).toHaveAttribute("aria-pressed", "false");
  });

  it("takes yours off a chip you're in, and adds you to one you're not", async () => {
    render(
      <ReactionChips
        roomName="checkout"
        messageId="m1"
        reactions={[
          { emoji: "🎉", by: ["julia"] },
          { emoji: "👀", by: ["lead"] },
        ]}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "🎉 from you" }));
    await userEvent.click(screen.getByRole("button", { name: "👀 from @lead" }));
    await waitFor(() => expect(reactToMessage).toHaveBeenCalledTimes(2));
    expect(reactToMessage).toHaveBeenNthCalledWith(1, "checkout", "m1", { emoji: "🎉", on: false, sender_handle: "julia" });
    expect(reactToMessage).toHaveBeenNthCalledWith(2, "checkout", "m1", { emoji: "👀", on: true, sender_handle: "julia" });
  });
});

describe("whoReacted", () => {
  it("names everyone up to three, then counts the rest", () => {
    expect(whoReacted(["lead"], "julia")).toBe("@lead");
    expect(whoReacted(["lead", "julia"], "julia")).toBe("@lead and you");
    expect(whoReacted(["a", "b", "c"], "julia")).toBe("@a, @b and @c");
    expect(whoReacted(["a", "b", "c", "d"], "julia")).toBe("@a, @b and 2 others");
  });
});
