// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { act, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithSWR } from "@/test/swr";

vi.mock("@/lib/api", () => ({
  fetchRoomAgents: vi.fn(),
  fetchRoomMembers: vi.fn(),
  fetchRoomPeople: vi.fn(),
  fetchMessages: vi.fn(),
  fetchMemories: vi.fn(),
  fetchSkills: vi.fn(),
  fetchPlan: vi.fn(),
  fetchEpisodes: vi.fn(),
  fetchRoom: vi.fn(),
  fetchRooms: vi.fn(),
  fetchNetworkStatus: vi.fn(),
  logFetchError: () => () => undefined,
}));

import { fetchMessages, fetchRoomAgents, fetchRoomMembers, fetchRoomPeople } from "@/lib/api";
import { CurrentUserProvider } from "@/components/current-user";
import { useRoomMessages, useRoomRevalidate, useRoomRoster, useThreadMessages } from "@/lib/room-data";

const agent = (handle: string, extra: Record<string, unknown> = {}) => ({
  handle,
  adapter: "claude_code",
  kind: null,
  description: "",
  cwd: null,
  owner: null,
  team: null,
  allow_from: [],
  ...extra,
});

/** A roster consumer for testing cache dedup (two instances should share one request). */
function Roster({ room, testId }: { room: string; testId: string }) {
  const { agents, people, others, subscriptions } = useRoomRoster(room);
  return (
    <ul data-testid={testId}>
      {agents.map((a) => (
        <li key={`agent-${a.handle}`}>{`agent:${a.handle}`}</li>
      ))}
      {[...subscriptions].map(([handle, subs]) => (
        <li key={`subscribed-${handle}`}>{`subscribed:${handle}:${subs.map((s) => s.describe).join("+")}`}</li>
      ))}
      {people.map((p) => (
        <li key={`person-${p.handle}`}>
          {`person:${p.handle}:${p.via}${p.you ? ":you" : ""}${p.owns ? ":owns" : ""}` +
            `${p.presence ? `:${p.presence.kind}` : ""}${p.teams.length ? `:${p.teams.join("+")}` : ""}`}
        </li>
      ))}
      {others.map((o) => (
        <li key={`other-${o.handle}`}>{`other:${o.handle}`}</li>
      ))}
    </ul>
  );
}

function Revalidator({ room }: { room: string }) {
  const revalidate = useRoomRevalidate(room);
  return (
    <button type="button" onClick={revalidate}>
      refresh
    </button>
  );
}

function renderRoster(ui: React.ReactElement) {
  return renderWithSWR(<CurrentUserProvider>{ui}</CurrentUserProvider>);
}

describe("useRoomRoster", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.mocked(fetchRoomAgents).mockReset().mockResolvedValue([
      agent("aligner", { adapter: "engine", kind: "aligner" }),
      agent("bob-code", { owner: "Bob", team: "platform" }),
    ]);
    vi.mocked(fetchRoomMembers).mockReset().mockResolvedValue({
      members: [
        { handle: "aligner", kind: "slim", last_seen: null },
        { handle: "watcher", kind: "lease", last_seen: "2026-08-20T00:00:00Z" },
      ],
      floors: [],
      subscriptions: [
        { id: "a1", handle: "Bob-Code", kind: "task", target: "work/x", describe: "work/x", until: null },
        { id: "a2", handle: "bob-code", kind: "notice", target: "resolved", describe: "resolved notices", until: null },
      ],
    });
    vi.mocked(fetchRoomPeople).mockReset().mockResolvedValue({
      people: [
        { handle: "bob", joined_at: "2026-10-01T00:00:00Z", via: "created" },
        { handle: "julia", joined_at: "2026-10-02T00:00:00Z", via: "message" },
        // Recorded before its manifest was written: drawn as the agent it is.
        { handle: "bob-code", joined_at: "2026-10-02T00:00:00Z", via: "seeded" },
      ],
      agents: [],
      engines: [],
      others: [{ handle: "watcher", holds_task: false, present: true }],
    });
    vi.mocked(fetchMessages).mockReset();
  });

  it("serves two consumers of the same room from one request per resource", async () => {
    renderRoster(
      <>
        <Roster room="demo" testId="composer" />
        <Roster room="demo" testId="rail" />
      </>,
    );

    await waitFor(() => expect(screen.getAllByText("agent:aligner")).toHaveLength(2));
    expect(fetchRoomAgents).toHaveBeenCalledTimes(1);
    expect(fetchRoomMembers).toHaveBeenCalledTimes(1);
    expect(fetchRoomPeople).toHaveBeenCalledTimes(1);
  });

  it("groups what each agent subscribed to under its handle, for its hover card", async () => {
    renderRoster(<Roster room="demo" testId="rail" />);
    expect(await screen.findByText("subscribed:bob-code:work/x+resolved notices")).toBeInTheDocument();
  });

  it("lists the people the hub recorded, never guessed from who posted or is present", async () => {
    window.localStorage.setItem("mycelium.principal", "julia");
    renderRoster(<Roster room="demo" testId="rail" />);

    // Their teams roll up from the agents they own.
    expect(await screen.findByText("person:bob:created:owns:platform")).toBeInTheDocument();
    expect(screen.getByText("person:julia:message:you")).toBeInTheDocument();
    // Present but neither a person nor an agent: listed as another, not a person.
    expect(screen.getByText("other:watcher")).toBeInTheDocument();
    expect(screen.queryByText(/^person:watcher/)).not.toBeInTheDocument();
    // An agent is listed as an agent, never twice.
    expect(screen.queryByText(/^person:bob-code/)).not.toBeInTheDocument();
    expect(screen.queryByText(/^person:aligner/)).not.toBeInTheDocument();
    // Messages aren't read to find people at all.
    expect(fetchMessages).not.toHaveBeenCalled();
  });

  it("refetches every consumer of a room when the room is revalidated", async () => {
    renderRoster(
      <>
        <Roster room="demo" testId="rail" />
        <Revalidator room="demo" />
      </>,
    );
    await waitFor(() => expect(fetchRoomAgents).toHaveBeenCalledTimes(1));

    await act(async () => {
      screen.getByRole("button", { name: "refresh" }).click();
    });

    await waitFor(() => expect(fetchRoomAgents).toHaveBeenCalledTimes(2));
    expect(fetchRoomMembers).toHaveBeenCalledTimes(2);
    expect(fetchRoomPeople).toHaveBeenCalledTimes(2);
  });

  it("keeps rooms apart: a second room is its own set of requests", async () => {
    renderRoster(
      <>
        <Roster room="demo" testId="rail" />
        <Roster room="other" testId="other" />
      </>,
    );

    await waitFor(() => expect(fetchRoomAgents).toHaveBeenCalledTimes(2));
    expect(vi.mocked(fetchRoomAgents).mock.calls.map(([room]) => room)).toEqual(["demo", "other"]);
  });
});

/** Two readers of the same room's messages: the channel, and one thread's pane. */
function Feeds({ room, episode }: { room: string; episode: string }) {
  const { messages } = useRoomMessages(room, 200);
  const thread = useThreadMessages(room, episode, 200);
  return (
    <>
      <ul data-testid="room">{messages.map((m, i) => <li key={i}>{String(m.content)}</li>)}</ul>
      <ul data-testid="thread">{thread.messages.map((m, i) => <li key={i}>{String(m.content)}</li>)}</ul>
    </>
  );
}

describe("useThreadMessages", () => {
  const EPISODE = "urn:ioc:mycelium:episode:demo:t3aa11bb";

  beforeEach(() => {
    vi.mocked(fetchMessages).mockReset();
    vi.mocked(fetchMessages).mockImplementation(async (_room, _limit, query) =>
      query?.episode
        ? { messages: [{ content: "inside the task" }] }
        : { messages: [{ content: "in the room" }] },
    );
  });

  it("keeps its own cache entry, so a thread never overwrites the room's feed", async () => {
    // A shared key would have the pane's filtered slice served to the channel —
    // the room emptied by the mechanism that exists to keep it readable.
    renderWithSWR(<Feeds room="demo" episode={EPISODE} />);
    await waitFor(() => expect(screen.getByTestId("thread")).toHaveTextContent("inside the task"));
    expect(screen.getByTestId("room")).toHaveTextContent("in the room");
    expect(screen.getByTestId("room")).not.toHaveTextContent("inside the task");
  });

  it("narrows on the server rather than filtering the room's page", async () => {
    renderWithSWR(<Feeds room="demo" episode={EPISODE} />);
    await waitFor(() => expect(fetchMessages).toHaveBeenCalledTimes(2));
    expect(vi.mocked(fetchMessages).mock.calls.map(([, , query]) => query?.episode)).toEqual([
      undefined,
      EPISODE,
    ]);
  });

  it("is reached by the room's revalidation, so an SSE thread write refreshes both", async () => {
    renderWithSWR(
      <>
        <Feeds room="demo" episode={EPISODE} />
        <Revalidator room="demo" />
      </>,
    );
    await waitFor(() => expect(fetchMessages).toHaveBeenCalledTimes(2));

    await act(async () => {
      screen.getByRole("button", { name: "refresh" }).click();
    });

    await waitFor(() => expect(fetchMessages).toHaveBeenCalledTimes(4));
  });

  it("fetches nothing while no thread is open", async () => {
    function Closed() {
      const { messages } = useThreadMessages("demo", null);
      return <span data-testid="closed">{messages.length}</span>;
    }
    renderWithSWR(<Closed />);
    await waitFor(() => expect(screen.getByTestId("closed")).toHaveTextContent("0"));
    expect(fetchMessages).not.toHaveBeenCalled();
  });

  /** A thread pane that shows how deep it has read and can ask for more. */
  function Pane({ room, episode }: { room: string; episode: string }) {
    const { messages, hasOlder, loadOlder } = useThreadMessages(room, episode, 2);
    return (
      <>
        <ul data-testid="pane">{messages.map((m, i) => <li key={i}>{String(m.content)}</li>)}</ul>
        {hasOlder && (
          <button type="button" onClick={loadOlder}>
            older
          </button>
        )}
      </>
    );
  }

  it("widens its window rather than paging behind a cursor", async () => {
    // Newest-first, so the newest N always contains the newest M before it:
    // widening is idempotent against the live stream in the way an offset is
    // not, and it stays one cache entry — which is what keeps a pushed write
    // reaching this pane through `useRoomRevalidate`.
    const thread = ["third", "second", "first"];
    vi.mocked(fetchMessages).mockImplementation(async (_room, limit) => ({
      messages: thread.slice(0, limit).map((content) => ({ content })),
      total: thread.length,
    }));

    renderWithSWR(<Pane room="demo" episode={EPISODE} />);
    await waitFor(() => expect(screen.getByTestId("pane")).toHaveTextContent("second"));
    expect(screen.getByTestId("pane")).not.toHaveTextContent("first");

    await act(async () => {
      screen.getByRole("button", { name: "older" }).click();
    });

    await waitFor(() => expect(screen.getByTestId("pane")).toHaveTextContent("first"));
    expect(vi.mocked(fetchMessages).mock.calls.map(([, limit]) => limit)).toEqual([2, 4]);
  });

  it("offers more only while the room says there is more", async () => {
    // `total` is what matched, not what was returned, so this is exact rather
    // than a full page inferred to mean there is another behind it.
    vi.mocked(fetchMessages).mockResolvedValue({
      messages: [{ content: "third" }, { content: "second" }],
      total: 2,
    });

    renderWithSWR(<Pane room="demo" episode={EPISODE} />);
    await waitFor(() => expect(screen.getByTestId("pane")).toHaveTextContent("second"));
    expect(screen.queryByRole("button", { name: "older" })).not.toBeInTheDocument();
  });
});
