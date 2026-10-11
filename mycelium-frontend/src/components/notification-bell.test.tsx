// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { act } from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { FakeEventSource } from "@/test/fake-event-source";
import { resetStreamHub } from "@/lib/stream-hub";

vi.mock("@/lib/api", () => ({
  // bob owns the agent "builder"; the room's one row is filed by it.
  fetchRoomAgents: vi.fn(async () => [{ handle: "builder", owner: "bob" }]),
  fetchMemories: vi.fn(async () => [
    {
      key: "work/zoom",
      created_by: "builder",
      value: "Zoom and pan images",
      meta: { status: "open" },
      episode: "urn:ioc:mycelium:episode:sprint:t1",
    },
  ]),
}));

import { CurrentUserProvider } from "@/components/current-user";
import { NotificationsProvider } from "@/components/notifications-provider";
import { NotificationBell } from "@/components/notification-bell";

const THREAD = "urn:ioc:mycelium:episode:sprint:t1";
let seq = 0;
const at = () => `2026-10-11T10:${String(10 + seq).padStart(2, "0")}:00.000000+00:00`;

function renderBell() {
  return render(
    <CurrentUserProvider>
      <NotificationsProvider>
        <NotificationBell />
      </NotificationsProvider>
    </CurrentUserProvider>,
  );
}

function message(sender: string, text: string, episode: string | null = null) {
  seq += 1;
  return {
    id: `msg-${seq}`,
    room_name: "sprint",
    sender_handle: sender,
    message_type: "l9_exchange",
    created_at: at(),
    episode,
    content: JSON.stringify({ content: text }),
  };
}

function upstream(change: string) {
  seq += 1;
  return {
    id: `n-${seq}`,
    room_name: "sprint",
    sender_handle: "system",
    message_type: "l9_exchange",
    created_at: at(),
    content: JSON.stringify({
      l9: {
        payload: {
          type: "notice",
          data: { subkind: "upstream", change, key: "work/zoom", title: "Zoom and pan images", episode: THREAD, ref: "o/r#1258" },
        },
      },
    }),
  };
}

async function emit(...frames: Record<string, unknown>[]) {
  const es = FakeEventSource.latest();
  for (const f of frames) {
    await act(async () => {
      es.emitNotification(f);
    });
  }
}

async function start() {
  renderBell();
  await act(async () => {});
  await act(async () => {
    FakeEventSource.latest().open();
  });
}

describe("<NotificationBell />", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.localStorage.setItem("mycelium.principal", "bob");
    resetStreamHub();
    FakeEventSource.reset();
    vi.stubGlobal("EventSource", FakeEventSource);
  });

  it("lists a question put to you under Needs you and counts it on the badge", async () => {
    const user = userEvent.setup();
    await start();
    await emit(message("alice", "hey @bob take a look"));

    await user.click(await screen.findByLabelText("1 waiting on you"));
    const needsYou = await screen.findByRole("region", { name: "Needs you" });
    expect(within(needsYou).getByText("sprint channel")).toBeInTheDocument();
    expect(within(needsYou).getByText("Asks you")).toBeInTheDocument();
    expect(within(needsYou).getByText(/hey @bob take a look/)).toBeInTheDocument();
  });

  it("ignores the channel's chatter that doesn't name you", async () => {
    await start();
    await emit(message("alice", "hey @carol take a look"));
    expect(screen.getByLabelText("Notifications")).toBeInTheDocument();
  });

  it("puts a silent mention in the bell without counting it", async () => {
    const user = userEvent.setup();
    await start();
    await emit(message("alice", "done, for @~bob", THREAD));

    await user.click(screen.getByLabelText("Notifications"));
    const earlier = await screen.findByRole("region", { name: "Earlier" });
    expect(within(earlier).getByText("Zoom and pan images")).toBeInTheDocument();
    expect(within(earlier).getByText("alice named you")).toBeInTheDocument();
  });

  it("groups a task's updates into one entry that ends ready to merge", async () => {
    const user = userEvent.setup();
    await start();
    // Filed by bob's own agent, so the task is his to hear about.
    await emit(upstream("opened"), upstream("approved"), upstream("ci_passed"));

    await user.click(await screen.findByLabelText("1 waiting on you"));
    const needsYou = await screen.findByRole("region", { name: "Needs you" });
    expect(within(needsYou).getAllByText("Zoom and pan images")).toHaveLength(1);
    expect(within(needsYou).getByText("Ready to merge")).toBeInTheDocument();
    expect(within(needsYou).getByText("CI green")).toBeInTheDocument();
    expect(within(needsYou).getByRole("link")).toHaveAttribute("href", "/room/sprint?focus=episode%3At1");
  });

  it("answering in the thread takes it off Needs you", async () => {
    const user = userEvent.setup();
    await start();
    await emit(message("alice", "@bob which one?", THREAD));
    await screen.findByLabelText("1 waiting on you");
    await emit(message("bob", "the second", THREAD));

    await user.click(await screen.findByLabelText("Notifications"));
    expect(screen.queryByRole("region", { name: "Needs you" })).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Earlier" })).toBeInTheDocument();
  });

  it("muting a task takes it out of the bell", async () => {
    const user = userEvent.setup();
    await start();
    await emit(message("alice", "hey @bob take a look"));
    await user.click(await screen.findByLabelText("1 waiting on you"));

    await user.click(await screen.findByLabelText("Mute sprint channel"));
    expect(screen.queryByText("sprint channel")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Notifications")).toBeInTheDocument();
  });
});
