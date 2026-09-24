// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { screen, waitFor } from "@testing-library/react";
import { renderWithSWR } from "@/test/swr";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const sendRoomMessage = vi.fn().mockResolvedValue(undefined);
const createTask = vi.fn().mockResolvedValue({ key: "work/fix-the-flaky-tests", episode: "urn:e:t1" });
const writeFields = vi.fn().mockResolvedValue({});

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

vi.mock("@/lib/api", () => ({
  logFetchError: () => () => undefined,
  sendRoomMessage: (...args: unknown[]) => sendRoomMessage(...args),
  createTask: (...args: unknown[]) => createTask(...args),
  writeFields: (...args: unknown[]) => writeFields(...args),
  startSwarm: vi.fn(),
  fetchRoomAgents: vi.fn().mockResolvedValue([
    { handle: "aligner", adapter: "engine", kind: "aligner", description: "mediator", cwd: null, owner: null, team: null, allow_from: [] },
  ]),
  fetchRoomMembers: vi.fn().mockResolvedValue({
    members: [
      { handle: "watcher", kind: "lease", last_seen: null },
      { handle: "aligner", kind: "slim", last_seen: null },
    ],
    floors: [],
  }),
  fetchMessages: vi.fn().mockResolvedValue({
    messages: [
      { message_type: "broadcast", sender_handle: "sam" },
      { message_type: "broadcast", sender_handle: "aligner" },
    ],
  }),
  fetchMemories: vi.fn().mockResolvedValue([
    { key: "decisions/db", value: "", version: 2, created_by: "julia", updated_at: "" },
    { key: "context/goals", value: "", version: 1, created_by: "sam", updated_at: "" },
  ]),
  fetchSkills: vi.fn().mockResolvedValue([
    { name: "summarize-room", description: "condense decisions", body: "", version: 1, created_by: "julia", created_at: "", updated_at: "" },
  ]),
}));

vi.mock("@/components/current-user", () => ({
  useCurrentUser: () => ({ principal: "julia" }),
}));

vi.mock("@/components/keymap-provider", () => ({
  useKeyAction: () => undefined,
}));

import { RoomChatBox } from "@/components/room-chat-box";

async function textarea() {
  return await screen.findByPlaceholderText(/Message the room/);
}

describe("<RoomChatBox /> composer triggers", () => {
  beforeEach(() => {
    sendRoomMessage.mockClear();
  });

  it("autocompletes a memory on [[ and inserts [[key]]", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = await textarea();
    await userEvent.click(box);
    // `[` is a special char in userEvent.type — double it to type a literal `[[`.
    await userEvent.type(box, "see [[[[db");

    const option = await screen.findByRole("button", { name: /\[\[decisions\/db\]\]/ });
    await userEvent.click(option);

    expect((box as HTMLTextAreaElement).value).toContain("[[decisions/db]] ");
  });

  it("autocompletes a skill on / and inserts /name", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = await textarea();
    await userEvent.click(box);
    await userEvent.type(box, "/sum");

    const option = await screen.findByRole("button", { name: /\/summarize-room/ });
    await userEvent.click(option);

    expect((box as HTMLTextAreaElement).value).toContain("/summarize-room ");
  });

  it("still autocompletes an @agent mention", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = await textarea();
    await userEvent.click(box);
    await userEvent.type(box, "@ali");

    const option = await screen.findByRole("button", { name: /@aligner/ });
    await userEvent.click(option);

    expect((box as HTMLTextAreaElement).value).toContain("@aligner ");
  });

  it("also autocompletes a person (present member), not just agents", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = await textarea();
    await userEvent.click(box);
    await userEvent.type(box, "@wat");

    const option = await screen.findByRole("button", { name: /@watcher/ });
    await userEvent.click(option);

    expect((box as HTMLTextAreaElement).value).toContain("@watcher ");
  });

  it("autocompletes a poster who isn't currently present (Members-panel parity)", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = await textarea();
    await userEvent.click(box);
    await userEvent.type(box, "@sam");

    const option = await screen.findByRole("button", { name: /@sam/ });
    await userEvent.click(option);

    expect((box as HTMLTextAreaElement).value).toContain("@sam ");
  });

  it("does not open a skill popover for a slash inside a word (e.g. a path)", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = await textarea();
    await userEvent.click(box);
    await userEvent.type(box, "path/sum");

    // The `/` is preceded by a non-space, so it is not a skill trigger.
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: /\/summarize-room/ })).toBeNull();
    });
  });
});

describe("<RoomChatBox /> commands", () => {
  beforeEach(() => {
    sendRoomMessage.mockClear();
    createTask.mockClear();
    writeFields.mockClear();
  });

  it("lists the commands ahead of the skills, only as the message's first word", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = await textarea();
    await userEvent.click(box);
    await userEvent.type(box, "/");

    expect(await screen.findByRole("button", { name: /\/task.*command/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /\/swarm.*command/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /\/summarize-room/ })).toBeInTheDocument();

    await userEvent.clear(box);
    await userEvent.type(box, "see /");
    await screen.findByRole("button", { name: /\/summarize-room/ });
    expect(screen.queryByRole("button", { name: /\/task/ })).toBeNull();
  });

  it("files /task as a task on the board instead of posting it", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = await textarea();
    await userEvent.click(box);
    await userEvent.type(box, "/task fix the flaky tests @agent-2 !! #ci{Enter}");

    await waitFor(() => expect(createTask).toHaveBeenCalled());
    expect(createTask).toHaveBeenCalledWith("demo", {
      title: "fix the flaky tests",
      handle: "julia",
      assignee: "agent-2",
    });
    expect(writeFields).toHaveBeenCalledWith("demo", {
      key: "work/fix-the-flaky-tests",
      handle: "julia",
      fields: { priority: "urgent", tags: ["ci"] },
    });
    expect(sendRoomMessage).not.toHaveBeenCalled();
    expect((box as HTMLTextAreaElement).value).toBe("");
  });

  it("opens the swarm dialog for /swarm, with the task filled in", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = await textarea();
    await userEvent.click(box);
    await userEvent.type(box, "/swarm write the 2.0 release notes{Enter}");

    expect(await screen.findByRole("dialog", { name: "Start a swarm" })).toBeInTheDocument();
    expect(screen.getByLabelText("What should the team work on?")).toHaveValue(
      "write the 2.0 release notes",
    );
    expect(sendRoomMessage).not.toHaveBeenCalled();
  });

  it("asks what the task is when a command comes with nothing", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = await textarea();
    await userEvent.click(box);
    await userEvent.type(box, "/task{Escape}{Enter}");

    expect(await screen.findByText(/Say what it is: \/task/)).toBeInTheDocument();
    expect(createTask).not.toHaveBeenCalled();
  });
});

describe("<RoomChatBox /> targeting", () => {
  beforeEach(() => {
    sendRoomMessage.mockClear();
  });

  it("writes to the room when no thread is named", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = await textarea();
    await userEvent.type(box, "morning{Enter}");
    await waitFor(() => expect(sendRoomMessage).toHaveBeenCalled());
    expect(sendRoomMessage.mock.calls[0][1]).toMatchObject({ content: "morning", episode: null });
  });

  it("writes into the thread it was pointed at", async () => {
    const episode = "urn:ioc:mycelium:episode:demo:t3aa11bb";
    renderWithSWR(<RoomChatBox roomName="demo" episode={episode} threadLabel="flip reads" />);
    // Where it lands is the one thing the composer must not be coy about: the
    // same box writes both places, and the difference is whether an argument
    // stays inside a task or becomes the room's.
    const box = await screen.findByPlaceholderText(/Reply in flip reads/);
    await userEvent.type(box, "gating on the lag alarm{Enter}");
    await waitFor(() => expect(sendRoomMessage).toHaveBeenCalled());
    expect(sendRoomMessage.mock.calls[0][1]).toMatchObject({
      content: "gating on the lag alarm",
      episode,
    });
  });

  it("still says it is a thread when nothing named it", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" episode="urn:ioc:mycelium:episode:demo:t9" />);
    expect(await screen.findByPlaceholderText(/Reply in this thread/)).toBeInTheDocument();
  });
});
