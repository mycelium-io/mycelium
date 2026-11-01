// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithSWR } from "@/test/swr";

const searchMemories = vi.fn();
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  searchMemories: (...a: unknown[]) => searchMemories(...a),
}));
const messageSearch = vi.fn();
vi.mock("@/lib/room-data", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/room-data")>()),
  useMessageSearch: (room: string, query: string) => messageSearch(room, query),
}));

import { Findable } from "./findable";

beforeEach(() => {
  searchMemories.mockReset().mockResolvedValue([]);
  messageSearch.mockReset().mockReturnValue({ result: null, error: undefined, loading: false });
  Element.prototype.scrollIntoView = vi.fn();
});

const VIEW = (
  <article>
    <p>Ship the checkout on Friday.</p>
    <p>The checkout needs one more review.</p>
  </article>
);

describe("<Findable />", () => {
  it("stays out of the way until ⌘F asks for it", () => {
    renderWithSWR(<Findable request={0} label="Find in this memory">{VIEW}</Findable>);
    expect(screen.queryByLabelText("Find in this memory")).not.toBeInTheDocument();
  });

  it("finds in what the view shows and steps between the hits", async () => {
    renderWithSWR(<Findable request={1} label="Find in this memory">{VIEW}</Findable>);
    const input = screen.getByLabelText("Find in this memory");
    expect(input).toHaveFocus();

    await userEvent.type(input, "checkout");
    await waitFor(() => expect(screen.getByText("1/2")).toBeInTheDocument());
    await userEvent.keyboard("{Enter}");
    expect(screen.getByText("2/2")).toBeInTheDocument();
    await userEvent.keyboard("{Enter}");
    expect(screen.getByText("1/2")).toBeInTheDocument();

    await userEvent.keyboard("{Escape}");
    expect(screen.queryByLabelText("Find in this memory")).not.toBeInTheDocument();
  });

  it("lists the room's memories as History, and opens one", async () => {
    searchMemories.mockResolvedValue([
      { memory: { key: "decisions/checkout", value: "# Checkout cutover", version: 1, created_by: "a", updated_at: "" }, similarity: 0.8 },
    ]);
    const onOpen = vi.fn();
    renderWithSWR(
      <Findable request={1} label="Find in this memory" history={{ kind: "memories", room: "atlas", onOpen }}>
        {VIEW}
      </Findable>,
    );
    await userEvent.type(screen.getByLabelText("Find in this memory"), "checkout");

    await userEvent.click(await screen.findByRole("button", { name: /decisions\/checkout/ }));
    expect(onOpen).toHaveBeenCalledWith("decisions/checkout");
    expect(searchMemories).toHaveBeenCalledWith("atlas", "checkout");
  });

  it("scopes a thread's History to the thread", async () => {
    renderWithSWR(
      <Findable
        request={1}
        label="Find in this thread"
        history={{ kind: "messages", room: "atlas", scope: "thread:urn:e:t1", about: "", onOpenHit: vi.fn() }}
      >
        {VIEW}
      </Findable>,
    );
    await userEvent.type(screen.getByLabelText("Find in this thread"), "review");
    await waitFor(() => expect(messageSearch).toHaveBeenLastCalledWith("atlas", "thread:urn:e:t1 review"));
  });
});
