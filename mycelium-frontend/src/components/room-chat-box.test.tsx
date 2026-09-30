// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { screen, waitFor } from "@testing-library/react";
import { renderWithSWR } from "@/test/swr";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const sendRoomMessage = vi.fn().mockResolvedValue(undefined);
const createTask = vi.fn().mockResolvedValue({ key: "work/fix-the-flaky-tests", episode: "urn:e:t1" });
const writeFields = vi.fn().mockResolvedValue({});
const createMemories = vi.fn().mockResolvedValue(undefined);
const launchRunnerAgent = vi.fn().mockResolvedValue({ id: "job1" });
const createEngine = vi.fn().mockResolvedValue({ handle: "aligner" });

const framework = (id: string, name: string) => ({
  id,
  name,
  command: id,
  path: null,
  version: null,
  installed: true,
  launchable: true,
  note: null,
});
const LAPTOP = {
  id: "laptop-1",
  label: "laptop",
  owner: "julia",
  platform: "darwin",
  version: "",
  herdr: true,
  host: "herdr",
  roots: ["/Users/julia/code"],
  frameworks: [framework("claude-code", "Claude Code"), framework("codex", "Codex")],
  agents: [],
  connected: true,
  last_seen: "",
  started_at: "",
};

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

vi.mock("@/lib/api", () => ({
  logFetchError: () => () => undefined,
  fetchUsers: async () => [],
  sendRoomMessage: (...args: unknown[]) => sendRoomMessage(...args),
  createTask: (...args: unknown[]) => createTask(...args),
  writeFields: (...args: unknown[]) => writeFields(...args),
  startSwarm: vi.fn(),
  fetchRunners: async () => [LAPTOP],
  fetchRunnerJob: vi.fn().mockResolvedValue({ id: "job1", status: "queued", error: null }),
  launchRunnerAgent: (...args: unknown[]) => launchRunnerAgent(...args),
  createEngine: (...args: unknown[]) => createEngine(...args),
  createMemories: (...args: unknown[]) => createMemories(...args),
  fetchRoomAgents: vi.fn().mockResolvedValue([
    { handle: "aligner", adapter: "engine", kind: "aligner", description: "mediator", cwd: null, owner: null, team: null, allow_from: [] },
    { handle: "conductor", adapter: "engine", kind: "conductor", description: "", cwd: null, owner: null, team: null, allow_from: [] },
  ]),
  fetchProtocols: async () => [
    { name: "gated", description: "A proposer proposes, a guardian approves or blocks.", roles: ["proposer", "guardian"], source: "builtin" },
    { name: "concord", description: "Help them agree.", roles: [], source: "builtin" },
  ],
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
  usePrincipal: () => "julia",
}));

vi.mock("@/components/keymap-provider", () => ({
  useKeyAction: () => undefined,
}));

import { RoomChatBox } from "@/components/room-chat-box";

// A draft outlives its composer, which is the point, so each case starts
// with none rather than inheriting the last one's typing.
beforeEach(() => {
  window.localStorage.clear();
});

async function textarea() {
  return await screen.findByPlaceholderText(/Message the room/);
}

describe("<RoomChatBox /> drafts", () => {
  beforeEach(() => {
    sendRoomMessage.mockClear();
  });

  it("keeps what was typed in a room when you leave and come back", async () => {
    const { rerender } = renderWithSWR(<RoomChatBox roomName="demo" />);
    await userEvent.type(await textarea(), "half a thought");

    rerender(<RoomChatBox roomName="other" />);
    await waitFor(async () => expect(await textarea()).toHaveValue(""));
    await userEvent.type(await textarea(), "elsewhere");

    rerender(<RoomChatBox roomName="demo" />);
    await waitFor(async () => expect(await textarea()).toHaveValue("half a thought"));
    rerender(<RoomChatBox roomName="other" />);
    await waitFor(async () => expect(await textarea()).toHaveValue("elsewhere"));
  });

  it("keeps a thread's draft apart from its room's, and forgets it once sent", async () => {
    const { rerender } = renderWithSWR(<RoomChatBox roomName="demo" episode="urn:e:t1" />);
    await userEvent.type(await screen.findByRole("textbox"), "for the task");

    rerender(<RoomChatBox roomName="demo" />);
    await waitFor(async () => expect(await textarea()).toHaveValue(""));

    rerender(<RoomChatBox roomName="demo" episode="urn:e:t1" />);
    const box = await screen.findByRole("textbox");
    await waitFor(() => expect(box).toHaveValue("for the task"));
    await userEvent.type(box, "{Enter}");
    await waitFor(() => expect(sendRoomMessage).toHaveBeenCalled());
    await waitFor(() => expect(window.localStorage.getItem("mycelium.draft:demo#urn:e:t1")).toBeNull());
  });
});

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
    createMemories.mockClear();
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

  it("opens the new-memory editor for a /memory with nothing to write yet, where its key points", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = await textarea();
    await userEvent.click(box);
    await userEvent.type(box, "/memory procedures/launch-checklist{Enter}");

    expect(await screen.findByRole("dialog", { name: /New memory in/ })).toBeInTheDocument();
    expect(screen.getByLabelText("Title")).toHaveValue("launch checklist");
    expect(screen.getByLabelText("Folder")).toHaveValue("procedures");
    expect(sendRoomMessage).not.toHaveBeenCalled();
    expect((box as HTMLTextAreaElement).value).toBe("");
  });

  it("writes a /memory with text straight to the room", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = await textarea();
    await userEvent.click(box);
    await userEvent.type(box, "/memory con");
    // A folder completes without a space, and what's in it is offered next.
    expect(await screen.findByRole("button", { name: /context\/.*folder/ })).toBeInTheDocument();
    await userEvent.keyboard("{Tab}");
    expect(box).toHaveValue("/memory context/");
    expect(await screen.findByRole("button", { name: /context\/goals.*replaces/ })).toBeInTheDocument();

    await userEvent.type(box, "launch-plan Ship on Tuesday{Enter}");
    await waitFor(() => expect(createMemories).toHaveBeenCalled());
    expect(createMemories).toHaveBeenCalledWith("demo", [
      { key: "context/launch-plan", value: "Ship on Tuesday", content_text: "Ship on Tuesday", created_by: "julia" },
    ]);
    expect(await screen.findByRole("status")).toHaveTextContent("Saved context/launch-plan.");
  });

  it("replaces a memory only at the version it saw", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = await textarea();
    await userEvent.click(box);
    await userEvent.type(box, "/memory ");
    await screen.findByRole("button", { name: /context\// });
    await userEvent.type(box, "decisions/db Postgres, not SQLite{Enter}");
    await waitFor(() => expect(createMemories).toHaveBeenCalled());
    expect(createMemories.mock.calls[0][1][0]).toMatchObject({ key: "decisions/db", base_version: 2 });
    expect(await screen.findByRole("status")).toHaveTextContent("Updated decisions/db.");
  });

  it("says what a key can be when it can't be one", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = await textarea();
    await userEvent.click(box);
    await userEvent.type(box, "/memory Launch checklist{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("The key is folder/name");
    expect(createMemories).not.toHaveBeenCalled();
  });

  it("offers a task, a memory or an agent from the +", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    await userEvent.click(await screen.findByRole("button", { name: "Add to the room" }));

    expect(await screen.findByRole("button", { name: /Task or flow…/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Agent…/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Memory…/ }));
    expect(await screen.findByRole("dialog", { name: /New memory in/ })).toBeInTheDocument();
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

describe("<RoomChatBox /> command arguments", () => {
  beforeEach(() => {
    sendRoomMessage.mockClear();
    launchRunnerAgent.mockClear();
    createEngine.mockClear();
  });

  it("draws the signature with the argument being typed lit", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = await textarea();
    await userEvent.click(box);
    await userEvent.type(box, "/agent ");

    const usage = await screen.findByLabelText("/agent usage");
    expect(usage).toHaveTextContent("/agent<handle><harness>[folder][machine]");
    expect(usage.querySelector("[aria-current]")).toHaveTextContent("<handle>");
    expect(usage).toHaveTextContent("What the room calls it");

    await userEvent.type(box, "scout ");
    expect(usage.querySelector("[aria-current]")).toHaveTextContent("<harness>");
  });

  it("completes a harness with Tab and starts the agent on the machine", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = await textarea();
    await userEvent.click(box);
    await userEvent.type(box, "/agent scout cl");

    expect(await screen.findByRole("button", { name: /claude-code.*Claude Code on laptop/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^codex/ })).toBeNull();
    await userEvent.keyboard("{Tab}");
    expect(box).toHaveValue("/agent scout claude-code ");

    // The optional folder offers the machine's; Enter on it untyped still sends.
    expect(await screen.findByRole("button", { name: /~\/code/ })).toBeInTheDocument();
    await userEvent.keyboard("{Enter}");

    await waitFor(() => expect(launchRunnerAgent).toHaveBeenCalled());
    expect(launchRunnerAgent).toHaveBeenCalledWith("laptop-1", {
      room: "demo",
      handle: "scout",
      framework: "claude-code",
      cwd: undefined,
      created_by: "julia",
    });
    expect(sendRoomMessage).not.toHaveBeenCalled();
    expect(await screen.findByText("@scout: Waiting for the machine")).toBeInTheDocument();
    expect(box).toHaveValue("");
  });

  it("picks from the list with Enter, before anything is typed", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = await textarea();
    await userEvent.click(box);
    await userEvent.type(box, "/agent scout ");
    await screen.findByRole("button", { name: /claude-code/ });
    await userEvent.keyboard("{ArrowDown}{Enter}");

    expect(box).toHaveValue("/agent scout codex ");
    expect(launchRunnerAgent).not.toHaveBeenCalled();
  });

  it("expands a folder typed from home", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = await textarea();
    await userEvent.click(box);
    await userEvent.type(box, "/agent @Scout ");
    await screen.findByRole("button", { name: /codex/ });
    await userEvent.type(box, "codex ~/code/app{Enter}");

    await waitFor(() => expect(launchRunnerAgent).toHaveBeenCalled());
    expect(launchRunnerAgent.mock.calls[0][1]).toMatchObject({
      handle: "scout",
      framework: "codex",
      cwd: "/Users/julia/code/app",
    });
  });

  it("says what the machine can start instead of queuing what it can't", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = await textarea();
    await userEvent.click(box);
    await userEvent.type(box, "/agent scout ");
    await screen.findByRole("button", { name: /claude-code/ });
    await userEvent.type(box, "gemini{Enter}");

    expect(await screen.findByRole("alert")).toHaveTextContent("laptop can't start gemini. It can start claude-code, codex.");
    expect(launchRunnerAgent).not.toHaveBeenCalled();
    expect(box).toHaveValue("/agent scout gemini");
  });

  it("names the argument left out", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = await textarea();
    await userEvent.click(box);
    await userEvent.type(box, "/agent scout{Enter}");

    expect(await screen.findByRole("alert")).toHaveTextContent("Say the harness: /agent <handle> <harness>");
    expect(launchRunnerAgent).not.toHaveBeenCalled();
  });

  it("adds an engine, its kind completed and its handle defaulted", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = await textarea();
    await userEvent.click(box);
    await userEvent.type(box, "/engine al");
    expect(await screen.findByRole("button", { name: /aligner.*Mediates/ })).toBeInTheDocument();
    await userEvent.keyboard("{Tab}{Enter}");

    await waitFor(() => expect(createEngine).toHaveBeenCalled());
    expect(createEngine).toHaveBeenCalledWith("demo", {
      handle: "aligner",
      kind: "aligner",
      description: "",
      created_by: "julia",
    });
    expect(await screen.findByRole("status")).toHaveTextContent("Added @aligner");
  });

  it("does not offer members for a handle being made up", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = await textarea();
    await userEvent.click(box);
    await userEvent.type(box, "/agent @al");
    await screen.findByLabelText("/agent usage");
    expect(screen.queryByRole("button", { name: /@aligner/ })).toBeNull();
  });
});

describe("<RoomChatBox /> conductor summons", () => {
  beforeEach(() => {
    sendRoomMessage.mockClear();
  });
  const thread = "urn:ioc:mycelium:episode:demo:t1";

  it("completes the flow, then lights its roles in the order they bind", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" episode={thread} threadLabel="the fix" />);
    const box = await screen.findByPlaceholderText(/Reply in the fix/);
    await userEvent.click(box);
    await userEvent.type(box, "@conductor ");

    const usage = await screen.findByLabelText("@conductor usage");
    expect(usage.querySelector("[aria-current]")).toHaveTextContent("<flow>");
    // Each flow says who it asks for, which is what tells them apart.
    expect(await screen.findByRole("button", { name: /gated.*@proposer @guardian/ })).toBeInTheDocument();
    await userEvent.type(box, "ga");
    await userEvent.keyboard("{Tab}");
    expect(box).toHaveValue("@conductor gated ");

    expect(usage).toHaveTextContent("@conductorgated@proposer@guardian<what…>");
    expect(usage.querySelector("[aria-current]")).toHaveTextContent("@proposer");
    expect(usage).toHaveTextContent("Who plays proposer");

    await userEvent.type(box, "@sam ");
    expect(usage.querySelector("[aria-current]")).toHaveTextContent("@guardian");
    await userEvent.type(box, "@watcher ");
    expect(usage.querySelector("[aria-current]")).toHaveTextContent("<what…>");
    expect(usage).not.toHaveTextContent("inside a task");

    // It is still a message: the conductor reads it where it lands.
    await userEvent.type(box, "ship the fix{Enter}");
    await waitFor(() => expect(sendRoomMessage).toHaveBeenCalled());
    expect(sendRoomMessage.mock.calls[0][1]).toMatchObject({
      content: "@conductor gated @sam @watcher ship the fix",
      episode: thread,
    });
  });

  it("says a flow needs a task when it's summoned in the room", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = await textarea();
    await userEvent.click(box);
    await userEvent.type(box, "@conductor concord ");
    expect(await screen.findByLabelText("@conductor usage")).toHaveTextContent(
      "A flow runs inside a task",
    );
  });

  it("names a flow the room doesn't have", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" episode={thread} />);
    const box = await screen.findByPlaceholderText(/Reply in this thread/);
    await userEvent.click(box);
    await userEvent.type(box, "@conductor ");
    await screen.findByRole("button", { name: /gated/ });
    await userEvent.type(box, "nope ");
    expect(await screen.findByLabelText("@conductor usage")).toHaveTextContent("There's no nope flow");
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
