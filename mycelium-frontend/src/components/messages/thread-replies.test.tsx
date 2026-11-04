// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ThreadReplies } from "@/components/messages/thread-replies";
import type { MessageThread } from "@/lib/room-data";

const thread = (over: Partial<MessageThread> = {}): MessageThread => ({
  key: "threads/when-should-the-payment-alert-fire",
  episode: "urn:ioc:mycelium:episode:checkout:e7a1c3",
  title: "When should the payment alert fire?",
  from: "h6",
  replies: { replies: 0, repliers: [] },
  task: null,
  ...over,
});

describe("<ThreadReplies />", () => {
  it("reads Thread until someone replies", () => {
    render(<ThreadReplies thread={thread()} />);
    expect(screen.getByRole("button", { name: /no replies yet/ })).toHaveTextContent("Thread");
  });

  it("says how many replied, who, the newest reply and opens the thread", async () => {
    const onOpen = vi.fn();
    render(
      <ThreadReplies
        onOpen={onOpen}
        thread={thread({
          replies: {
            replies: 3,
            repliers: ["operator", "builder"],
            last_reply: "send it to the room and to my phone",
            last_reply_at: new Date().toISOString(),
          },
        })}
      />,
    );
    const line = screen.getByRole("button", { name: /3 replies/ });
    expect(line).toHaveTextContent("3 replies");
    expect(line).toHaveTextContent("send it to the room and to my phone");
    await userEvent.click(line);
    expect(onOpen).toHaveBeenCalledWith("urn:ioc:mycelium:episode:checkout:e7a1c3");
  });

  it("links the task made from it", async () => {
    const onOpen = vi.fn();
    const task = { key: "work/payment-alert", title: "Add the payment alert", episode: "urn:e:task" };
    render(<ThreadReplies onOpen={onOpen} thread={thread({ task })} />);
    await userEvent.click(screen.getByRole("button", { name: 'Open the task "Add the payment alert"' }));
    expect(onOpen).toHaveBeenCalledWith("urn:e:task");
  });
});
