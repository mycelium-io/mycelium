// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const createTask = vi.fn().mockResolvedValue({ key: "work/ship-it", episode: "urn:e:t9" });
const copyText = vi.fn().mockResolvedValue(undefined);

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  createTask: (...args: unknown[]) => createTask(...args),
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

// The room page declares its keys live; a message's keys are among them.
function InRoom() {
  useKeyScope("room");
  return null;
}

function Row(props: { onOpenThread?: (episode: string) => void; time?: string }) {
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
  copyText.mockClear();
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
    await userEvent.click(screen.getByRole("button", { name: "Reply" }));
    await userEvent.click(screen.getByRole("button", { name: "Quote" }));
    // A message in the channel, so the room's own composer takes them.
    expect(seen).toEqual([
      { room: "demo", episode: null, text: "@builder " },
      { room: "demo", episode: null, text: "> @~builder: stripe payments are merged\n\n" },
    ]);
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
    expect(seen.at(-1)).toEqual({ room: "demo", episode: null, text: "@builder " });
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
