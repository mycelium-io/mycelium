// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { act, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithSWR } from "@/test/swr";

vi.mock("@/lib/api", () => ({
  fetchRoomAgents: vi.fn(),
  fetchRoomMembers: vi.fn(),
  fetchMessages: vi.fn(),
  fetchMemories: vi.fn(),
  fetchMemoryIntegrity: vi.fn(),
  fetchSkills: vi.fn(),
  fetchPlan: vi.fn(),
  fetchEpisodes: vi.fn(),
  fetchRoom: vi.fn(),
  fetchRooms: vi.fn(),
  fetchNetworkStatus: vi.fn(),
  logFetchError: () => () => undefined,
}));

import { fetchMessages, fetchRoomAgents, fetchRoomMembers } from "@/lib/api";
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
  const { agents, people } = useRoomRoster(room);
  return (
    <ul data-testid={testId}>
      {agents.map((a) => (
        <li key={`agent-${a.handle}`}>{`agent:${a.handle}`}</li>
      ))}
      {people.map((p) => (
        <li key={`person-${p.handle}`}>
          {`person:${p.handle}${p.you ? ":you" : ""}${p.owns ? ":owns" : ""}` +
            `${p.presence ? `:${p.presence.kind}` : ""}${p.teams.length ? `:${p.teams.join("+")}` : ""}`}
        </li>
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
    vi.mocked(fetchRoomMembers).mockReset().mockResolvedValue([
      { handle: "aligner", kind: "slim", last_seen: null },
      { handle: "watcher", kind: "lease", last_seen: "2026-08-20T00:00:00Z" },
    ]);
    vi.mocked(fetchMessages).mockReset().mockResolvedValue({
      messages: [
        { message_type: "broadcast", sender_handle: "sam" },
        { message_type: "broadcast", sender_handle: "aligner" },
        { message_type: "l9_exchange", sender_handle: "ignored" },
      ],
    });
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
    expect(fetchMessages).toHaveBeenCalledTimes(1);
  });

  it("unions people from owners, posters, presence and the acting-as handle", async () => {
    window.localStorage.setItem("mycelium.principal", "julia");
    renderRoster(<Roster room="demo" testId="rail" />);

    // An owner is a person even when they've never posted, and their teams roll
    // up from the agents they own.
    expect(await screen.findByText("person:bob:owns:platform")).toBeInTheDocument();
    // A poster, and someone present only through an `await` lease.
    expect(screen.getByText("person:sam")).toBeInTheDocument();
    expect(screen.getByText("person:watcher:lease")).toBeInTheDocument();
    expect(screen.getByText("person:julia:you")).toBeInTheDocument();
    // An agent that posted or is present is listed as an agent, never twice.
    expect(screen.queryByText(/^person:aligner/)).not.toBeInTheDocument();
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
    expect(fetchMessages).toHaveBeenCalledTimes(2);
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
});
