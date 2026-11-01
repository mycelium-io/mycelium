// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { JumpToLatest } from "@/components/jump-to-latest";

// The behavior behind it is `messages/use-follow-latest.test.tsx`.
describe("<JumpToLatest />", () => {
  it("says how many messages are new, or just Jump to latest", () => {
    const onClick = vi.fn();
    const { rerender } = render(<JumpToLatest unread={0} onClick={onClick} />);
    fireEvent.click(screen.getByRole("button", { name: "Jump to latest" }));
    expect(onClick).toHaveBeenCalledOnce();
    rerender(<JumpToLatest unread={3} onClick={onClick} />);
    expect(screen.getByRole("button", { name: "Jump to latest, 3 new" })).toHaveTextContent("3 new messages");
  });
});
