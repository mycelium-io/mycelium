// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { createRef, useState } from "react";
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

  it("names the room-wide count, and History opens and closes the list", async () => {
    const onToggle = vi.fn();
    bar({ history: { total: 42, loading: false, failed: false, open: false, onToggle, problems: [] } });

    const toggle = screen.getByRole("button", { name: "Search history, 42 matches" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(toggle);
    expect(onToggle).toHaveBeenCalled();
  });

  it("says what the hub couldn't read", () => {
    bar({ history: { total: 0, loading: false, failed: false, open: true, onToggle: vi.fn(), problems: ["after:someday"] } });
    expect(screen.getByText(/Couldn.t read “after:someday”/)).toBeInTheDocument();
  });

  it("does not offer to step when there is nothing to step to", () => {
    bar({ count: 0, position: null });

    expect(screen.getByText("No matches")).toBeInTheDocument();
    expect(screen.getByLabelText("Next match")).toBeDisabled();
    expect(screen.getByLabelText("Previous match")).toBeDisabled();
  });
});

/** The bar holding its own query, as the channel does, so typing is real. */
function Typed({ seen }: { seen?: Parameters<typeof ChatFindBar>[0]["seen"] }) {
  const [query, setQuery] = useState("");
  return (
    <>
      <ChatFindBar
        query={query}
        onQueryChange={setQuery}
        count={0}
        position={null}
        onStep={() => {}}
        onClose={() => {}}
        inputRef={createRef<HTMLInputElement>()}
        partial={false}
        seen={seen}
        handles={["builder", "reviewer"]}
      />
      <output data-testid="query">{query}</output>
    </>
  );
}

describe("<ChatFindBar /> hints", () => {
  it("completes a field name with Tab, then offers that field's values", async () => {
    render(<Typed seen={{ from: [{ value: "operator", label: "operator", count: 9 }] }} />);
    const input = screen.getByLabelText("Find in the channel");

    await userEvent.type(input, "fr");
    expect(screen.getByRole("button", { name: /from:/ })).toBeInTheDocument();
    await userEvent.keyboard("{Tab}");
    expect(screen.getByTestId("query")).toHaveTextContent("from:");

    // The room's senders first, with how many messages each, then the roster.
    expect(screen.getByRole("button", { name: /operator.*9 messages/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /builder/ })).toBeInTheDocument();
    expect(screen.getByLabelText("Search field")).toHaveTextContent("who said it");
    await userEvent.keyboard("{Tab}");
    expect(screen.getByTestId("query").textContent).toBe("from:operator ");
  });

  it("offers a closed field's whole set, and nothing for a plain word", async () => {
    render(<Typed />);
    const input = screen.getByLabelText("Find in the channel");

    await userEvent.type(input, "has:");
    for (const v of ["mention", "link", "memory", "code", "scores"]) {
      expect(screen.getByRole("button", { name: new RegExp(`^${v}`) })).toBeInTheDocument();
    }
    await userEvent.clear(input);
    await userEvent.type(input, "apple");
    expect(screen.queryByLabelText("Search suggestions")).not.toBeInTheDocument();
  });
});
