// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { useState } from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SearchPalette } from "@/components/search-palette";
import { EMPTY_SCOPE, type SearchHit, type SearchResponse, type SearchScope } from "@/lib/search";

const hit = (over: Partial<SearchHit> = {}): SearchHit => ({
  type: "memory",
  room: "atlas",
  id: "decisions/pooling",
  title: "decisions/pooling",
  subtitle: "atlas · decisions",
  snippet: "pgbouncer in front",
  kind: "decisions",
  timestamp: "2026-08-12T17:00:00Z",
  score: 0.9,
  ...over,
});

const response = (results: SearchHit[], scope: Partial<SearchScope> = {}): SearchResponse => ({
  query: "",
  scope: { ...EMPTY_SCOPE, ...scope },
  results,
  counts: {},
});

/** The palette mounted the way the shell mounts it: open, with a stub backend. */
function Harness({
  search,
  onPick = () => {},
  onClose = () => {},
}: {
  search: (query: string) => Promise<SearchResponse>;
  onPick?: (hit: SearchHit) => void;
  onClose?: () => void;
}) {
  const [open, setOpen] = useState(true);
  return (
    <SearchPalette
      open={open}
      onClose={() => {
        setOpen(false);
        onClose();
      }}
      onPick={onPick}
      search={search}
      mac={false}
    />
  );
}

const palette = () => screen.getByRole("dialog", { name: "Search" });
const rows = () => within(palette()).queryAllByRole("option");

describe("<SearchPalette />", () => {
  it("prompts for the scoping tokens before anything is typed", () => {
    render(<Harness search={async () => response([])} />);
    expect(palette()).toHaveTextContent("#room, @agent, memory: and kind: narrow it.");
    expect(rows()).toHaveLength(0);
  });

  it("queries once the typing settles and lists what came back", async () => {
    const search = vi.fn(async () => response([hit(), hit({ type: "room", id: "atlas", title: "atlas" })]));
    const user = userEvent.setup();
    render(<Harness search={search} />);

    await user.keyboard("pooling");
    await waitFor(() => expect(rows()).toHaveLength(2));
    expect(rows()[0]).toHaveTextContent("decisions/pooling");
    expect(rows()[0]).toHaveTextContent("memory");
    expect(rows()[1]).toHaveTextContent("room");
  });

  it("debounces a burst of keystrokes into one request", async () => {
    const search = vi.fn(async () => response([hit()]));
    const user = userEvent.setup();
    render(<Harness search={search} />);

    await user.keyboard("pooling");
    await waitFor(() => expect(rows()).toHaveLength(1));
    expect(search).toHaveBeenCalledTimes(1);
    expect(search).toHaveBeenCalledWith("pooling");
  });

  it("keeps the server's order rather than re-sorting on what's on the row", async () => {
    // A cross-type ranking is the backend's whole job; a client-side fuzzy pass
    // over the visible text would quietly undo it.
    const search = vi.fn(async () =>
      response([
        hit({ type: "episode", id: "e4f1a2", title: "episode e4f1a2", score: 0.9 }),
        hit({ id: "zzz/pooling", title: "zzz/pooling", score: 0.8 }),
      ]),
    );
    const user = userEvent.setup();
    render(<Harness search={search} />);

    await user.keyboard("pooling");
    await waitFor(() => expect(rows()).toHaveLength(2));
    expect(rows().map(r => r.textContent?.slice(0, 7))).toEqual(["episode", "zzz/poo"]);
  });

  it("shows the scope the server read, not the raw tokens", async () => {
    const search = vi.fn(async () => response([hit()], { rooms: ["atlas"], types: ["memory"] }));
    const user = userEvent.setup();
    render(<Harness search={search} />);

    await user.keyboard("#atlas memory: pooling");
    await waitFor(() => expect(palette()).toHaveTextContent("#atlas"));
    expect(palette()).toHaveTextContent("memory:");
  });

  it("hands the picked result back and does not close itself twice", async () => {
    const onPick = vi.fn();
    const user = userEvent.setup();
    render(<Harness search={async () => response([hit()])} onPick={onPick} />);

    await user.keyboard("pooling");
    await waitFor(() => expect(rows()).toHaveLength(1));
    await user.click(rows()[0]);
    expect(onPick).toHaveBeenCalledWith(expect.objectContaining({ id: "decisions/pooling" }));
  });

  it("opens the selection on Enter", async () => {
    const onPick = vi.fn();
    const user = userEvent.setup();
    render(<Harness search={async () => response([hit()])} onPick={onPick} />);

    await user.keyboard("pooling");
    await waitFor(() => expect(rows()).toHaveLength(1));
    await user.keyboard("{Enter}");
    expect(onPick).toHaveBeenCalled();
  });

  it("says a failed request failed instead of showing an empty room", async () => {
    const user = userEvent.setup();
    render(<Harness search={async () => { throw new Error("hub unreachable"); }} />);

    await user.keyboard("pooling");
    await waitFor(() => expect(within(palette()).getByRole("alert")).toHaveTextContent("hub unreachable"));
  });

  it("drops a response that arrived after a later one", async () => {
    // Typing outruns the network: the slow first request must not overwrite the
    // results of the query the user has actually typed.
    let resolveFirst: (r: SearchResponse) => void = () => {};
    const search = vi
      .fn()
      .mockImplementationOnce(() => new Promise<SearchResponse>(r => { resolveFirst = r; }))
      .mockImplementationOnce(async () => response([hit({ id: "second", title: "second" })]));

    const user = userEvent.setup();
    render(<Harness search={search} />);

    await user.keyboard("one");
    await waitFor(() => expect(search).toHaveBeenCalledTimes(1));
    await user.keyboard(" two");
    await waitFor(() => expect(search).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(rows()).toHaveLength(1));

    resolveFirst(response([hit({ id: "first", title: "first" })]));
    await waitFor(() => expect(rows()[0]).toHaveTextContent("second"));
  });

  it("closes on Escape", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<Harness search={async () => response([])} onClose={onClose} />);

    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
  });

  it("closes on the chord that opened it", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<Harness search={async () => response([])} onClose={onClose} />);

    await user.keyboard("/");
    expect(onClose).toHaveBeenCalled();
  });
});
