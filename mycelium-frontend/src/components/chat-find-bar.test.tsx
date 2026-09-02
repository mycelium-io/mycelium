// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { createRef } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ChatFindBar } from "@/components/chat-find-bar";

function bar(props: Partial<Parameters<typeof ChatFindBar>[0]> = {}) {
  const onStep = vi.fn();
  const onClose = vi.fn();
  const onQueryChange = vi.fn();
  render(
    <ChatFindBar
      query="deploy"
      onQueryChange={onQueryChange}
      count={3}
      position={0}
      onStep={onStep}
      onClose={onClose}
      inputRef={createRef<HTMLInputElement>()}
      partial={false}
      {...props}
    />,
  );
  return { onStep, onClose, onQueryChange };
}

describe("<ChatFindBar />", () => {
  it("counts from one, the way a find bar reads", () => {
    bar({ count: 3, position: 0 });
    expect(screen.getByText("1/3")).toBeInTheDocument();
  });

  it("shows nothing at all before there is a query", () => {
    bar({ query: "", count: 0, position: null });
    expect(screen.queryByText("No matches")).not.toBeInTheDocument();
  });

  it("steps forward on Enter and back on shift+Enter", async () => {
    const { onStep } = bar();
    const input = screen.getByLabelText("Find in the channel");

    await userEvent.type(input, "{Enter}");
    expect(onStep).toHaveBeenLastCalledWith(1);

    await userEvent.type(input, "{Shift>}{Enter}{/Shift}");
    expect(onStep).toHaveBeenLastCalledWith(-1);
  });

  it("closes on Escape rather than merely losing focus", async () => {
    const { onClose } = bar();

    await userEvent.type(screen.getByLabelText("Find in the channel"), "{Escape}");

    expect(onClose).toHaveBeenCalled();
  });

  it("says its reach is the loaded messages while pages remain unread", () => {
    bar({ partial: true });
    expect(screen.getByText("loaded only")).toBeInTheDocument();
  });

  it("does not offer to step when there is nothing to step to", () => {
    bar({ count: 0, position: null });

    expect(screen.getByText("No matches")).toBeInTheDocument();
    expect(screen.getByLabelText("Next match")).toBeDisabled();
    expect(screen.getByLabelText("Previous match")).toBeDisabled();
  });
});
