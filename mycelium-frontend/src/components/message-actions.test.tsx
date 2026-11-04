// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const createTask = vi.fn().mockResolvedValue({ key: "work/ship-it", episode: "urn:e:t9" });
const createThread = vi.fn().mockResolvedValue({ key: "threads/stripe-payments-are-merged", episode: "urn:e:th1" });
const copyText = vi.fn().mockResolvedValue(undefined);

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  createTask: (...args: unknown[]) => createTask(...args),
  createThread: (...args: unknown[]) => createThread(...args),
}));
vi.mock("@/lib/clipboard", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/clipboard")>()),
  copyText: (text: string) => copyText(text),
}));
vi.mock("@/components/current-user", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/current-user")>()),
  useCurrentUser: () => ({ principal: "julia" }),
}));

import { KeymapProvider, useKeyScope } from "@/components/keymap-provider";
import { MessageActions } from "@/components/message-actions";
import { COMPOSER_INSERT_EVENT, type ComposerInsert } from "@/lib/message-actions";
import type { MessageThread } from "@/lib/room-data";

// The room page declares its keys live; a message's keys are among them.
function InRoom() {
  useKeyScope("room");
  return null;
}

function Row(props: {
  onOpenThread?: (episode: string) => void;
  time?: string;
  threads?: boolean;
  thread?: MessageThread | null;
}) {
  return (
    <KeymapProvider>
      <InRoom />
      <div data-testid="row">
        <p>stripe payments are merged</p>
        <MessageActions roomName="demo" messageId="m1" content="stripe payments are merged" sender="builder" {...props} />
      </div>
    </KeymapProvider>
  );
}

function inserts(): ComposerInsert[] {
  const seen: ComposerInsert[] = [];
  window.addEventListener(COMPOSER_INSERT_EVENT, (e) => seen.push((e as CustomEvent<ComposerInsert>).detail));
  return seen;
}

beforeEach(() => {
  createTask.mockClear();
  createThread.mockClear();
  copyText.mockClear();
});

describe("<MessageActions /> threads", () => {
  const started: MessageThread = {
    key: "threads/stripe-payments-are-merged",
    episode: "urn:e:th1",
    title: "stripe payments are merged",
    from: "m1",
    replies: { replies: 2, repliers: ["reviewer"] },
    task: null,
  };

  it("orders the bar reply, quote, task, thread, then copy and link", () => {
    render(<Row threads />);
    fireEvent.mouseEnter(screen.getByTestId("row"));
    const names = screen.getAllByRole("button").map((b) => b.getAttribute("aria-label") ?? b.textContent);
    expect(names.slice(0, 6)).toEqual([
      "Reply to @builder",
      "Quote",
      "Make a task",
      "Start a thread",
      "Copy text",
      "Copy link",
    ]);
  });

  it("starts a thread from the message and opens it", async () => {
    const onOpenThread = vi.fn();
    render(<Row threads onOpenThread={onOpenThread} />);
    fireEvent.mouseEnter(screen.getByTestId("row"));
    await userEvent.click(screen.getByRole("button", { name: "Start a thread" }));
    await waitFor(() => expect(onOpenThread).toHaveBeenCalledWith("urn:e:th1"));
    expect(createThread).toHaveBeenCalledWith("demo", { from: "m1", handle: "julia" });
  });

  it("opens the thread a message already has, starting none", async () => {
    const onOpenThread = vi.fn();
    render(<Row threads thread={started} onOpenThread={onOpenThread} />);
    fireEvent.mouseEnter(screen.getByTestId("row"));
    await userEvent.click(screen.getByRole("button", { name: "Open the thread" }));
    expect(onOpenThread).toHaveBeenCalledWith("urn:e:th1");
    expect(createThread).not.toHaveBeenCalled();
  });

  it("says why when a thread can't be started", async () => {
    createThread.mockRejectedValueOnce(new Error("No message m1 in the channel"));
    render(<Row threads />);
    fireEvent.mouseEnter(screen.getByTestId("row"));
    await userEvent.click(screen.getByRole("button", { name: "Start a thread" }));
    expect(
      await screen.findByRole("button", { name: "Couldn't start the thread: No message m1 in the channel" }),
    ).toBeInTheDocument();
  });

  it("offers no thread inside one", () => {
    render(<Row />);
    fireEvent.mouseEnter(screen.getByTestId("row"));
    expect(screen.queryByRole("button", { name: "Start a thread" })).toBeNull();
  });
});

describe("<MessageActions />", () => {
  it("draws nothing until its message is hovered, and goes when the pointer leaves", () => {
    render(<Row />);
    expect(screen.queryByRole("toolbar")).toBeNull();
    fireEvent.mouseEnter(screen.getByTestId("row"));
    expect(screen.getByRole("toolbar", { name: "Message actions" })).toBeInTheDocument();
    fireEvent.mouseLeave(screen.getByTestId("row"));
    expect(screen.queryByRole("toolbar")).toBeNull();
  });

  it("replies and quotes into the room's composer", async () => {
    const seen = inserts();
    render(<Row />);
    fireEvent.mouseEnter(screen.getByTestId("row"));
    await userEvent.click(screen.getByRole("button", { name: "Reply to @builder" }));
    await userEvent.click(screen.getByRole("button", { name: "Quote" }));
    // A message in the channel, so the room's own composer takes them; each
    // says the row it came from, for a thread open in two places.
    const row = screen.getByTestId("row");
    expect(seen).toEqual([
      { room: "demo", episode: null, text: "@builder ", from: expect.any(HTMLElement) },
      {
        room: "demo",
        episode: null,
        text: "> @~builder: stripe payments are merged\n\n",
        from: expect.any(HTMLElement),
      },
    ]);
    expect(seen.every((d) => d.from && row.contains(d.from))).toBe(true);
  });

  it("answers R, Q and C only while its message is hovered", async () => {
    const seen = inserts();
    render(<Row />);
    await userEvent.keyboard("c");
    expect(copyText).not.toHaveBeenCalled();
    fireEvent.mouseEnter(screen.getByTestId("row"));
    await userEvent.keyboard("c");
    expect(copyText).toHaveBeenCalledWith("stripe payments are merged");
    await userEvent.keyboard("r");
    expect(seen.at(-1)).toMatchObject({ room: "demo", episode: null, text: "@builder " });
  });

  it("makes a task from the message and opens its thread", async () => {
    const onOpenThread = vi.fn();
    render(<Row onOpenThread={onOpenThread} />);
    fireEvent.mouseEnter(screen.getByTestId("row"));
    await userEvent.click(screen.getByRole("button", { name: "Make a task" }));
    await waitFor(() => expect(onOpenThread).toHaveBeenCalledWith("urn:e:t9"));
    expect(createTask).toHaveBeenCalledWith("demo", {
      title: "stripe payments are merged",
      content: expect.stringContaining("> stripe payments are merged\n\nFrom [a message](") as unknown as string,
      handle: "julia",
    });
  });

  it("shows a follow-up line's time in the bar", () => {
    render(<Row time="09:41" />);
    fireEvent.mouseEnter(screen.getByTestId("row"));
    expect(screen.getByRole("toolbar")).toHaveTextContent("09:41");
  });
});
