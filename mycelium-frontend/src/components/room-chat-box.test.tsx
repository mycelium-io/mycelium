// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { act, screen, waitFor } from "@testing-library/react";
import { renderWithSWR } from "@/test/swr";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const sendRoomMessage = vi.fn().mockResolvedValue(undefined);
const createTask = vi.fn().mockResolvedValue({ key: "work/fix-the-flaky-tests", episode: "urn:e:t1" });
const writeFields = vi.fn().mockResolvedValue({});
const createMemories = vi.fn().mockResolvedValue(undefined);
const createSchedule = vi.fn().mockResolvedValue(undefined);
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

// The real module underneath, so a read the composer starts making later
// falls through to it rather than failing every test here.
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
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
  createSchedule: (...args: unknown[]) => createSchedule(...args),
  fetchSchedules: async () => ({ schedules: [], checks: { always: "Every time" } }),
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
  fetchRoomPeople: vi.fn().mockResolvedValue({
    people: [{ handle: "sam", joined_at: "2026-10-01T00:00:00Z", via: "message" }],
    agents: [],
    engines: [],
    others: [{ handle: "watcher", holds_task: false, present: true }],
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
  fetchUploads: async () => ({ uploads: [], total: 0, accepted: ["png", "pdf", "md"], max_bytes: 1024 }),
  uploadFile: (room: string, file: File) => uploadFile(room, file),
  fetchMentionGroups: (room: string, episode: string | null) => fetchMentionGroups(room, episode),
}));

// A busy room: sam and five agents. In the task's thread, two agents are
// talking, so `@here` there is just those two. In the channel it's everyone.
const member = (handle: string, kind: "agent" | "person", status: "working" | "idle" | null = null, role: "posted" | null = null) => ({
  handle,
  kind,
  status,
  posted_at: role ? "2026-10-29T10:00:00Z" : null,
  role,
});
const EVERYONE = [
  member("sam", "person"),
  ...["builder", "reviewer", "pricing", "support", "refunds"].map((h) => member(h, "agent", "idle")),
];
const TALKING = [member("builder", "agent", "working", "posted"), member("reviewer", "agent", "idle", "posted")];
const fetchMentionGroups = vi.fn(async (_room: string, episode: string | null) => ({
  here: episode ? { count: 2, members: TALKING } : { count: 6, members: EVERYONE },
  all: { count: 6, members: EVERYONE },
}));

const uploadFile = vi.fn(async (_room: string, file: File) => ({
  name: file.name,
  key: `uploads/${file.name}`,
  filename: file.name,
  kind: "image",
  content_type: "image/png",
  size: file.size,
  sha256: "0".repeat(64),
  created_by: "julia",
  created_at: "",
  url: `/api/rooms/demo/uploads/${file.name}/raw`,
}));

vi.mock("@/components/current-user", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/current-user")>()),
  useCurrentUser: () => ({ principal: "julia" }),
  usePrincipal: () => "julia",
}));

vi.mock("@/components/keymap-provider", () => ({
  useKeyAction: () => undefined,
}));

// The real emoji list, unless a case turns `fail` on: then the list's chunk
// won't load, as when offline or after a deploy replaced it.
const emojiLoad = vi.hoisted(() => ({ fail: false }));
vi.mock("@/lib/emoji", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/emoji")>();
  const failing = () => Promise.reject(new Error("Loading chunk failed"));
  return {
    ...actual,
    emojiNow: () => (emojiLoad.fail ? null : actual.emojiNow()),
    loadEmoji: () => (emojiLoad.fail ? failing() : actual.loadEmoji()),
    withEmoji: (text: string, t: import("@/lib/emoji").EmojiTable | null) =>
      emojiLoad.fail ? actual.withEmoji(text, null, failing) : actual.withEmoji(text, t),
  };
});

import { RoomChatBox } from "@/components/room-chat-box";
import { recordMentions } from "@/lib/recent-mentions";
import { insertIntoComposer, quoteText, replyText } from "@/lib/message-actions";

// A draft outlives its composer, which is the point, so each case starts
// with none rather than inheriting the last one's typing.
beforeEach(() => {
  window.localStorage.clear();
});

async function textarea() {
  return await screen.findByPlaceholderText(/Message the room/);
}

describe("<RoomChatBox /> attachments", () => {
  beforeEach(() => {
    sendRoomMessage.mockClear();
    uploadFile.mockClear();
  });

  const picker = (container: HTMLElement) => container.querySelector<HTMLInputElement>('input[type="file"]')!;
  const png = (name: string) => new File(["png"], name, { type: "image/png" });

  it("uploads every file picked and sends the message linking each", async () => {
    const user = userEvent.setup();
    const { container } = renderWithSWR(<RoomChatBox roomName="demo" />);
    await user.upload(picker(container), [png("a.png"), png("b.png")]);
    await waitFor(() => expect(uploadFile).toHaveBeenCalledTimes(2));
    expect(await screen.findByLabelText("Remove a.png")).toBeInTheDocument();

    await user.type(await textarea(), "the mockups{Enter}");
    await waitFor(() => expect(sendRoomMessage).toHaveBeenCalled());
    expect(sendRoomMessage.mock.calls[0][1]).toMatchObject({
      content: "the mockups\n\n[[uploads/a.png]] [[uploads/b.png]]",
    });
    await waitFor(() => expect(screen.queryByLabelText("Remove a.png")).not.toBeInTheDocument());
  });

  it("offers only files from a thread's +, and opens the picker from it", async () => {
    const user = userEvent.setup();
    const { container } = renderWithSWR(<RoomChatBox roomName="demo" episode="urn:e:t1" />);
    const clicked = vi.spyOn(picker(container), "click");
    await user.click(await screen.findByRole("button", { name: "Add to this thread" }));
    expect(screen.queryByRole("button", { name: /Task or flow…/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Schedule…/ })).not.toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: /Files…/ }));
    expect(clicked).toHaveBeenCalled();
  });

  it("sends files with no text", async () => {
    const user = userEvent.setup();
    const { container } = renderWithSWR(<RoomChatBox roomName="demo" />);
    await user.upload(picker(container), png("shot.png"));
    const send = screen.getByRole("button", { name: "Send message" });
    await waitFor(() => expect(send).toBeEnabled());
    await user.click(send);
    await waitFor(() => expect(sendRoomMessage.mock.calls[0][1]).toMatchObject({ content: "[[uploads/shot.png]]" }));
  });

  it("says why a file won't go before sending it, and sends the rest", async () => {
    const user = userEvent.setup({ applyAccept: false });
    const { container } = renderWithSWR(<RoomChatBox roomName="demo" />);
    await waitFor(() => expect(picker(container).accept).toBe(".png,.pdf,.md"));
    await user.upload(picker(container), [new File(["MZ"], "tool.exe"), png("ok.png")]);
    expect(await screen.findByText(/\.exe files can't be previewed/)).toBeInTheDocument();
    await waitFor(() => expect(uploadFile).toHaveBeenCalledTimes(1));
    expect(uploadFile.mock.calls[0][1]).toMatchObject({ name: "ok.png" });
  });

  it("waits for a file still uploading", async () => {
    let finish: () => void = () => {};
    uploadFile.mockImplementationOnce(
      (_room, file) =>
        new Promise((resolve) => {
          finish = () =>
            resolve({ name: file.name, key: `uploads/${file.name}`, filename: file.name, kind: "image", content_type: "image/png", size: 3, sha256: "", created_by: "julia", created_at: "", url: "" });
        }),
    );
    const user = userEvent.setup();
    const { container } = renderWithSWR(<RoomChatBox roomName="demo" />);
    await user.upload(picker(container), png("big.png"));
    await user.type(await textarea(), "here{Enter}");
    expect(sendRoomMessage).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Send message" })).toBeDisabled();
    finish();
    await waitFor(() => expect(screen.getByRole("button", { name: "Send message" })).toBeEnabled());
  });
});

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

describe("<RoomChatBox /> sent history", () => {
  beforeEach(() => {
    sendRoomMessage.mockClear();
    window.localStorage.clear();
  });

  it("steps back through what you sent with Up, and forward to your draft with Down", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = await textarea();
    for (const text of ["first", "second", "third"]) {
      await userEvent.type(box, `${text}{Enter}`);
      await waitFor(() => expect(box).toHaveValue(""));
      await waitFor(() => expect(box).toBeEnabled());
    }
    expect(JSON.parse(window.localStorage.getItem("mycelium.sent:demo") ?? "[]")).toEqual([
      "first",
      "second",
      "third",
    ]);
    await userEvent.type(box, "half typed");
    // The first step back is from the start of the draft; after that the
    // recalled messages are unchanged, so each press steps again at once.
    (box as HTMLTextAreaElement).setSelectionRange(0, 0);

    await userEvent.keyboard("{ArrowUp}");
    expect(box).toHaveValue("third");
    await userEvent.keyboard("{ArrowUp}");
    expect(box).toHaveValue("second");
    await userEvent.keyboard("{ArrowUp}");
    expect(box).toHaveValue("first");
    // Nothing older: it stays put.
    await userEvent.keyboard("{ArrowUp}");
    expect(box).toHaveValue("first");

    await userEvent.keyboard("{ArrowDown}");
    expect(box).toHaveValue("second");
    await userEvent.keyboard("{ArrowDown}");
    expect(box).toHaveValue("third");
    await userEvent.keyboard("{ArrowDown}");
    expect(box).toHaveValue("half typed");
  });

  it("steps through history from anywhere in an unchanged recalled message", async () => {
    window.localStorage.setItem("mycelium.sent:demo", JSON.stringify(["older", "a recalled message"]));
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = (await textarea()) as HTMLTextAreaElement;
    await userEvent.click(box);
    await userEvent.keyboard("{ArrowUp}");
    expect(box).toHaveValue("a recalled message");
    box.setSelectionRange(4, 4);
    await userEvent.keyboard("{ArrowUp}");
    expect(box).toHaveValue("older");
  });

  it("moves the cursor as usual anywhere but the first character", async () => {
    window.localStorage.setItem("mycelium.sent:demo", JSON.stringify(["earlier"]));
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = await textarea();
    await userEvent.type(box, "line one{Shift>}{Enter}{/Shift}line two");
    await userEvent.keyboard("{ArrowUp}");
    expect(box).toHaveValue("line one\nline two");
  });

  it("doesn't recall from a long line that wraps, until the cursor is at its start", async () => {
    const long = "a long message that wraps onto several rows of the box";
    window.localStorage.setItem("mycelium.sent:demo", JSON.stringify(["earlier"]));
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = (await textarea()) as HTMLTextAreaElement;
    await userEvent.type(box, long);

    // No newline before the cursor, but it isn't at the start: Up moves it.
    box.setSelectionRange(5, 5);
    await userEvent.keyboard("{ArrowUp}");
    expect(box).toHaveValue(long);
    box.setSelectionRange(0, 0);
    await userEvent.keyboard("{ArrowUp}");
    expect(box).toHaveValue("earlier");

    // The recalled message is unchanged, so Down steps forward to the draft
    // from anywhere in it.
    box.setSelectionRange(2, 2);
    await userEvent.keyboard("{ArrowDown}");
    expect(box).toHaveValue(long);
  });

  it("keeps each room's history apart", async () => {
    window.localStorage.setItem("mycelium.sent:other", JSON.stringify(["over there"]));
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = await textarea();
    await userEvent.click(box);
    await userEvent.keyboard("{ArrowUp}");
    expect(box).toHaveValue("");
  });
});

describe("<RoomChatBox /> composer triggers", () => {
  beforeEach(() => {
    sendRoomMessage.mockClear();
  });

  it("draws each sigil in the hint row as a keycap", async () => {
    const { container } = renderWithSWR(<RoomChatBox roomName="demo" />);
    await textarea();
    const caps = [...container.querySelectorAll("kbd")].map((k) => k.textContent);
    expect(caps).toEqual(expect.arrayContaining(["@", "@~", "@!", "[[", "/", ":"]));
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

  it("autocompletes a silent @~mention as one", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = await textarea();
    await userEvent.click(box);
    await userEvent.type(box, "cc @~ali");

    const option = await screen.findByRole("button", { name: /@aligner/ });
    await userEvent.click(option);

    expect((box as HTMLTextAreaElement).value).toBe("cc @~aligner ");
  });

  it("autocompletes an interrupting @!mention as one", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = await textarea();
    await userEvent.click(box);
    await userEvent.type(box, "@!ali");

    const option = await screen.findByRole("button", { name: /@aligner/ });
    await userEvent.click(option);

    expect((box as HTMLTextAreaElement).value).toBe("@!aligner ");
  });

  it("turns a finished mention into an interrupt without doubling the handle", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = (await textarea()) as HTMLTextAreaElement;
    await userEvent.click(box);
    await userEvent.type(box, "@ali");
    await userEvent.click(await screen.findByRole("button", { name: /@aligner/ }));
    await userEvent.type(box, "hi");
    expect(box.value).toBe("@aligner hi");

    // Back to just after the @, add ! and pick with Enter.
    await userEvent.type(box, "!", { initialSelectionStart: 1, initialSelectionEnd: 1 });
    await screen.findByRole("button", { name: /@aligner/ });
    await userEvent.keyboard("{Enter}");

    expect(box.value).toBe("@!aligner hi");
    // The cursor is put back on the next frame, past the space already there.
    await waitFor(() => expect(box.selectionStart).toBe("@!aligner ".length));
  });

  it("filters by the whole handle and replaces it when the cursor is inside one", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = (await textarea()) as HTMLTextAreaElement;
    await userEvent.click(box);
    await userEvent.type(box, "ask @aligner now");
    // Delete the "g" in the handle, then put it back: the cursor is mid-handle.
    await userEvent.type(box, "{backspace}g", { initialSelectionStart: 9, initialSelectionEnd: 9 });
    await userEvent.click(await screen.findByRole("button", { name: /@aligner/ }));

    expect(box.value).toBe("ask @aligner now");
  });

  it("leaves a full stop after a handle alone when the cursor is inside it", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = (await textarea()) as HTMLTextAreaElement;
    await userEvent.click(box);
    await userEvent.type(box, "ask @aligner. Thanks");
    await userEvent.type(box, "{backspace}g", { initialSelectionStart: 9, initialSelectionEnd: 9 });
    await userEvent.click(await screen.findByRole("button", { name: /@aligner/ }));

    expect(box.value).toBe("ask @aligner. Thanks");
  });

  it("says in the popover, and aloud, when a mention is silent or interrupts", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = await textarea();
    const announced = () => screen.getByTestId("mention-mode-announce").textContent;
    await userEvent.click(box);

    // A plain @ says nothing new.
    await userEvent.type(box, "@ali");
    await screen.findByRole("button", { name: /@aligner/ });
    expect(screen.queryByTestId("mention-mode")).toBeNull();
    expect(announced()).toBe("");

    await userEvent.clear(box);
    await userEvent.type(box, "@~ali");
    await screen.findByRole("button", { name: /@aligner/ });
    expect(screen.getByTestId("mention-mode")).toHaveTextContent("Silentnames them without notifying");
    expect(announced()).toBe("Silent mention: names them without notifying");

    await userEvent.clear(box);
    await userEvent.type(box, "@!ali");
    const option = await screen.findByRole("button", { name: /@aligner/ });
    expect(screen.getByTestId("mention-mode")).toHaveTextContent("Interruptstops a working agent");
    expect(announced()).toBe("Interrupt mention: stops a working agent");
    // An engine only acts when mentioned, so an interrupt reaches it as a mention.
    expect(option).toHaveTextContent("mentioned as usual, not interrupted");
  });

  it("also autocompletes someone present who is neither a person nor an agent here", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = await textarea();
    await userEvent.click(box);
    await userEvent.type(box, "@wat");

    const option = await screen.findByRole("button", { name: /@watcher/ });
    await userEvent.click(option);

    expect((box as HTMLTextAreaElement).value).toContain("@watcher ");
  });

  it("lists whoever you mentioned last first", async () => {
    recordMentions("demo", ["sam"]);
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = await textarea();
    await userEvent.click(box);
    await userEvent.type(box, "@");

    await screen.findByRole("button", { name: /@sam/ });
    const options = screen.getAllByRole("button").filter((b) => /^@|@\w/.test(b.textContent ?? ""));
    expect(options[0]?.textContent).toMatch(/@sam/);
  });

  it("puts a handle you just mentioned at the top of the next @ list", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = await textarea();
    await userEvent.click(box);
    await userEvent.type(box, "@conductor hello{Enter}");
    await userEvent.type(box, "@");

    await screen.findByRole("button", { name: /@conductor/ });
    const options = screen.getAllByRole("button").filter((b) => /^@|@\w/.test(b.textContent ?? ""));
    expect(options[0]?.textContent).toMatch(/@conductor/);
  });

  it("autocompletes one of the room's people who isn't present (Members-panel parity)", async () => {
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

  it("starts a /thread as a context page and opens it on its discussion", async () => {
    const onOpenMemory = vi.fn();
    renderWithSWR(<RoomChatBox roomName="demo" onOpenMemory={onOpenMemory} />);
    const box = await textarea();
    await userEvent.click(box);
    await userEvent.type(box, "/thread Chat buddy{Enter}");

    await waitFor(() => expect(onOpenMemory).toHaveBeenCalledWith("context/chat-buddy"));
    expect(createMemories).toHaveBeenCalledWith("demo", [
      {
        key: "context/chat-buddy",
        value: "# Chat buddy",
        content_text: "# Chat buddy",
        created_by: "julia",
        base_version: 0,
      },
    ]);
    expect(sendRoomMessage).not.toHaveBeenCalled();
    expect((box as HTMLTextAreaElement).value).toBe("");
  });

  it("opens a /thread the hub says already exists, though this browser hadn't seen it", async () => {
    // Create-only is the hub's to enforce: the list here may not have loaded,
    // or someone may have made the page a moment ago.
    const { ApiError } = await import("@/lib/api");
    createMemories.mockRejectedValueOnce(new ApiError("stale_base", 409));
    const onOpenMemory = vi.fn();
    renderWithSWR(<RoomChatBox roomName="demo" onOpenMemory={onOpenMemory} />);
    const box = await textarea();
    await userEvent.click(box);
    await userEvent.type(box, "/thread Launch retro{Enter}");

    await waitFor(() => expect(onOpenMemory).toHaveBeenCalledWith("context/launch-retro"));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("opens a /thread that already has that name rather than replacing it", async () => {
    const onOpenMemory = vi.fn();
    renderWithSWR(<RoomChatBox roomName="demo" onOpenMemory={onOpenMemory} />);
    const box = await textarea();
    await userEvent.click(box);
    // The room's memories are loaded once the [[ list can offer them. (`[` is
    // special to userEvent.type; doubled, it types a literal one.)
    await userEvent.type(box, "[[[[goals");
    await screen.findByRole("button", { name: /\[\[context\/goals\]\]/ });
    await userEvent.clear(box);
    await userEvent.type(box, "/thread Goals{Enter}");

    await waitFor(() => expect(onOpenMemory).toHaveBeenCalledWith("context/goals"));
    expect(createMemories).not.toHaveBeenCalled();
  });

  it("says what's missing from a /thread with no title it can name", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = await textarea();
    await userEvent.click(box);
    await userEvent.type(box, "/thread !!!{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("so it has a name");
    expect(createMemories).not.toHaveBeenCalled();
  });

  it("says what a key can be when it can't be one", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = await textarea();
    await userEvent.click(box);
    await userEvent.type(box, "/memory Launch checklist{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("The key is folder/name");
    expect(createMemories).not.toHaveBeenCalled();
  });

  it("offers files, a task, a memory or an agent from the +", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    await userEvent.click(await screen.findByRole("button", { name: "Add to the room" }));

    expect(await screen.findByRole("button", { name: /Files…/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Task or flow…/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Agent…/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Memory…/ }));
    expect(await screen.findByRole("dialog", { name: /New memory in/ })).toBeInTheDocument();
  });

  it("opens the New Schedule form from the +", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    await userEvent.click(await screen.findByRole("button", { name: "Add to the room" }));
    await userEvent.click(await screen.findByRole("button", { name: /Schedule…/ }));
    expect(await screen.findByRole("dialog", { name: "New schedule" })).toBeInTheDocument();
  });

  it("opens the New Schedule form from /schedule with nothing after it", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = await textarea();
    await userEvent.click(box);
    await userEvent.type(box, "/schedule{Escape}{Enter}");
    expect(await screen.findByRole("dialog", { name: "New schedule" })).toBeInTheDocument();
  });

  it("fills the form from a one-line /schedule without saving it", async () => {
    createSchedule.mockClear();
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = await textarea();
    await userEvent.click(box);
    await userEvent.type(box, "/schedule @scout daily 08:15 check the board{Escape}{Enter}");
    const dialog = await screen.findByRole("dialog", { name: "New schedule" });
    expect(dialog).toHaveTextContent("every day at 08:15 UTC");
    expect(screen.getByDisplayValue("check the board")).toBeInTheDocument();
    expect(createSchedule).not.toHaveBeenCalled();
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

    // Members are named silently: bound to the roles, asked by the conductor in turn.
    expect(usage).toHaveTextContent("@conductorgated@~proposer@~guardian<what…>");
    expect(usage.querySelector("[aria-current]")).toHaveTextContent("@~proposer");
    expect(usage).toHaveTextContent("Who plays proposer. Type @~ to pick them");

    await userEvent.type(box, "@~sam ");
    expect(usage.querySelector("[aria-current]")).toHaveTextContent("@~guardian");
    await userEvent.type(box, "@~watcher ");
    expect(usage.querySelector("[aria-current]")).toHaveTextContent("<what…>");
    expect(usage).not.toHaveTextContent("inside a task");

    // It is still a message: the conductor reads it where it lands.
    await userEvent.type(box, "ship the fix{Enter}");
    await waitFor(() => expect(sendRoomMessage).toHaveBeenCalled());
    expect(sendRoomMessage.mock.calls[0][1]).toMatchObject({
      content: "@conductor gated @~sam @~watcher ship the fix",
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

describe("<RoomChatBox /> @here and @all", () => {
  beforeEach(() => {
    sendRoomMessage.mockClear();
  });

  it("offers the groups last in a task, with who @here reaches: the two talking, not the room", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" episode="urn:e:t1" threadLabel="flip reads" />);
    const box = await screen.findByPlaceholderText(/Reply in flip reads/);
    await userEvent.type(box, "@");

    const here = await screen.findByRole("button", { name: /@here.*2 in this task/ });
    const all = screen.getByRole("button", { name: /@all.*6 in the room/ });
    // After every member, so reaching many is never what Enter picks first.
    const options = screen.getAllByRole("button").filter((b) => /^@|@\w/.test(b.textContent ?? ""));
    expect(options.slice(-2)).toEqual([here, all]);
    expect(screen.queryByRole("dialog", { name: /Who @/ })).toBeNull();

    await userEvent.hover(here);
    const card = await screen.findByRole("dialog", { name: "Who @here reaches" });
    expect(card).toHaveTextContent("pings 2");
    expect(card).toHaveTextContent("builder");
    expect(card).toHaveTextContent("reviewer");
    expect(card).not.toHaveTextContent("pricing");
  });

  it("doesn't offer a group for letters it doesn't start with", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = await textarea();
    await userEvent.type(box, "@s");
    await screen.findByRole("button", { name: /@sam/ });
    expect(screen.queryByRole("button", { name: /@here|@all/ })).toBeNull();
  });

  it("counts only the agents an interrupt would stop", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" episode="urn:e:t1" threadLabel="flip reads" />);
    const box = await screen.findByPlaceholderText(/Reply in flip reads/);
    await userEvent.type(box, "@!");
    await userEvent.hover(await screen.findByRole("button", { name: /@here.*2 in this task/ }));
    const card = await screen.findByRole("dialog", { name: "Who @!here reaches" });
    expect(card).toHaveTextContent("interrupts 1");
  });

  it("asks before waking many agents, and sends as written on Enter", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = await textarea();
    await userEvent.type(box, "@all please upgrade today");
    await waitFor(() => expect(fetchMentionGroups).toHaveBeenCalled());
    await userEvent.type(box, "{Enter}");

    const warning = await screen.findByRole("alertdialog", { name: "Wake many agents?" });
    expect(warning).toHaveTextContent("This wakes 5 agents, and notifies 1 person.");
    expect(sendRoomMessage).not.toHaveBeenCalled();

    await userEvent.type(box, "{Enter}");
    await waitFor(() => expect(sendRoomMessage).toHaveBeenCalled());
    expect(sendRoomMessage.mock.calls[0][1]).toMatchObject({ content: "@all please upgrade today" });
  });

  it("sends silently from the warning, so nobody is woken", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = await textarea();
    await userEvent.type(box, "@all please upgrade today");
    await waitFor(() => expect(fetchMentionGroups).toHaveBeenCalled());
    await userEvent.type(box, "{Enter}");
    await userEvent.click(await screen.findByRole("button", { name: "Send silently" }));

    await waitFor(() => expect(sendRoomMessage).toHaveBeenCalled());
    expect(sendRoomMessage.mock.calls[0][1]).toMatchObject({ content: "@~all please upgrade today" });
  });

  it("sends a small group without asking", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" episode="urn:e:t1" threadLabel="flip reads" />);
    const box = await screen.findByPlaceholderText(/Reply in flip reads/);
    await userEvent.type(box, "@here can you two agree?");
    await waitFor(() => expect(fetchMentionGroups).toHaveBeenCalled());
    await userEvent.type(box, "{Enter}");

    await waitFor(() => expect(sendRoomMessage).toHaveBeenCalled());
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("never asks about a silent group", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = await textarea();
    await userEvent.type(box, "@~all for the record");
    await waitFor(() => expect(fetchMentionGroups).toHaveBeenCalled());
    await userEvent.type(box, "{Enter}");
    await waitFor(() => expect(sendRoomMessage).toHaveBeenCalled());
  });
});

describe("<RoomChatBox /> emoji", () => {
  beforeEach(() => {
    sendRoomMessage.mockClear();
  });

  it("offers :tada for :ta and inserts the emoji itself on Enter", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = await textarea();
    await userEvent.click(box);
    await userEvent.type(box, "shipped :ta");

    expect(await screen.findByRole("button", { name: /🎉\s+:tada:/ })).toBeInTheDocument();
    await userEvent.keyboard("{Enter}");
    expect(box).toHaveValue("shipped 🎉 ");
    expect(sendRoomMessage).not.toHaveBeenCalled();
  });

  it("moves through the list and picks with Tab, as @ does", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = await textarea();
    await userEvent.click(box);
    await userEvent.type(box, ":thumbs");
    const options = await screen.findAllByRole("button", { name: /:thumbs/ });
    expect(options.length).toBeGreaterThan(1);
    const second = options[1].textContent?.match(/^\S+/)?.[0];
    await userEvent.keyboard("{ArrowDown}{Tab}");
    expect(box).toHaveValue(`${second} `);
  });

  it("turns a whole :name: into its emoji when a space follows", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = await textarea();
    await userEvent.click(box);
    // The list loads with the first `:`; then the shortcode is typed out.
    await userEvent.type(box, "so :ta");
    await screen.findByRole("button", { name: /:tada:/ });
    await userEvent.type(box, "da: done");
    expect(box).toHaveValue("so 🎉 done");
  });

  it("still sends, as typed, when the emoji list can't load", async () => {
    emojiLoad.fail = true;
    try {
      renderWithSWR(<RoomChatBox roomName="demo" />);
      const box = await textarea();
      await userEvent.click(box);
      await userEvent.type(box, "build failed :x: on main{Enter}");
      await waitFor(() => expect(sendRoomMessage).toHaveBeenCalled());
      expect(sendRoomMessage.mock.calls[0][1]).toMatchObject({ content: "build failed :x: on main" });
    } finally {
      emojiLoad.fail = false;
    }
  });

  it("sends the emoji, not the shortcode", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = await textarea();
    await userEvent.click(box);
    await userEvent.type(box, "merged :+1:{Enter}");
    await waitFor(() => expect(sendRoomMessage).toHaveBeenCalled());
    expect(sendRoomMessage.mock.calls[0][1]).toMatchObject({ content: "merged 👍" });
  });

  it.each([["at 12:30"], ["see https://x"], ["a: b"], ["run `x :ta"], ["run `x :tada: y"]])("leaves %s alone", async (typed) => {
    renderWithSWR(<RoomChatBox roomName="demo" />);
    const box = await textarea();
    await userEvent.click(box);
    // Typed once to load the list, then cleared, so a miss isn't just the list loading.
    await userEvent.type(box, ":ta");
    await screen.findByRole("button", { name: /:tada:/ });
    await userEvent.clear(box);
    await userEvent.type(box, typed);
    expect(screen.queryByRole("button", { name: /:tada:|:taco:|:thirty/ })).toBeNull();
    expect(box).toHaveValue(typed);
  });
});

describe("<RoomChatBox /> reply and quote", () => {
  it("adds a message's reply and quote to the channel's draft, with the cursor after them", async () => {
    renderWithSWR(<RoomChatBox roomName="demo" receivesInserts />);
    const box = (await textarea()) as HTMLTextAreaElement;
    act(() => insertIntoComposer({ room: "demo", text: quoteText("ship it", "sam") }));
    act(() => insertIntoComposer({ room: "demo", text: replyText("sam") }));
    await waitFor(() => expect(box).toHaveValue("> @~sam: ship it\n\n@sam "));
    await waitFor(() => expect(box).toHaveFocus());
    expect(box.selectionStart).toBe(box.value.length);
  });

  it("leaves another room's composer, and one that doesn't take them, alone", async () => {
    renderWithSWR(
      <>
        <RoomChatBox roomName="demo" />
        <RoomChatBox roomName="other" receivesInserts />
      </>,
    );
    act(() => insertIntoComposer({ room: "demo", text: replyText("sam") }));
    const boxes = await screen.findAllByPlaceholderText(/Message the room/);
    await new Promise((r) => requestAnimationFrame(r));
    for (const box of boxes) expect(box).toHaveValue("");
  });

  it("puts a reply to a message in a thread into that thread's composer, not the room's", async () => {
    renderWithSWR(
      <>
        <RoomChatBox roomName="demo" receivesInserts />
        <RoomChatBox roomName="demo" episode="urn:ep:demo:t1" threadLabel="Fix login" />
        <RoomChatBox roomName="demo" episode="urn:ep:demo:t2" threadLabel="Ship it" />
      </>,
    );
    act(() => insertIntoComposer({ room: "demo", episode: "urn:ep:demo:t1", text: replyText("sam") }));
    const thread = await screen.findByPlaceholderText(/Reply in Fix login/);
    await waitFor(() => expect(thread).toHaveValue("@sam "));
    await waitFor(() => expect(thread).toHaveFocus());
    expect(screen.getByPlaceholderText(/Message the room/)).toHaveValue("");
    expect(screen.getByPlaceholderText(/Reply in Ship it/)).toHaveValue("");
    // One from the channel still goes to the room's.
    act(() => insertIntoComposer({ room: "demo", text: replyText("ana") }));
    await waitFor(() => expect(screen.getByPlaceholderText(/Message the room/)).toHaveValue("@ana "));
    expect(thread).toHaveValue("@sam ");
  });

  it("with a thread open in two places, fills only the composer beside the message clicked", async () => {
    renderWithSWR(
      <>
        <section data-thread="urn:ep:demo:t1" data-testid="pane">
          <p data-testid="pane-message">a message</p>
          <RoomChatBox roomName="demo" episode="urn:ep:demo:t1" threadLabel="in the pane" />
        </section>
        <section data-thread="urn:ep:demo:t1" data-testid="page">
          <p data-testid="page-message">the same message</p>
          <RoomChatBox roomName="demo" episode="urn:ep:demo:t1" threadLabel="on the page" />
        </section>
      </>,
    );
    const inPane = await screen.findByPlaceholderText(/Reply in in the pane/);
    const onPage = screen.getByPlaceholderText(/Reply in on the page/);
    const from = screen.getByTestId("page-message");
    act(() => insertIntoComposer({ room: "demo", episode: "urn:ep:demo:t1", text: replyText("sam"), from }));
    await waitFor(() => expect(onPage).toHaveValue("@sam "));
    expect(inPane).toHaveValue("");
  });
});
