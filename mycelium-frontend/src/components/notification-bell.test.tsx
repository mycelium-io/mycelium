// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { act } from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { FakeEventSource } from "@/test/fake-event-source";
import { resetStreamHub } from "@/lib/stream-hub";

const THREAD = "urn:ioc:mycelium:episode:sprint:t1";

vi.mock("@/lib/api", () => ({
  fetchMemories: vi.fn(async () => [{ key: "work/zoom", value: { text: "Zoom and pan images\n\nbody" }, episode: THREAD }]),
}));
const ping = vi.fn();
vi.mock("@/lib/audio-ping", () => ({ ping: (...a: unknown[]) => ping(...a), primeAudio: () => {} }));

import { CurrentUserProvider } from "@/components/current-user";
import { NotificationsProvider } from "@/components/notifications-provider";
import { NotificationBell } from "@/components/notification-bell";

const CREATED = "2026-08-15T10:00:00.000000+00:00";
let seq = 0;

function renderBell() {
  return render(
    <CurrentUserProvider>
      <NotificationsProvider>
        <NotificationBell />
      </NotificationsProvider>
    </CurrentUserProvider>,
  );
}

function message(text: string, episode: string | null = null) {
  seq += 1;
  return {
    id: `msg-${seq}`,
    room_name: "sprint",
    sender_handle: "alice",
    message_type: "l9_exchange",
    created_at: CREATED,
    episode,
    content: JSON.stringify({ content: text }),
  };
}

async function start() {
  renderBell();
  await act(async () => {});
  await act(async () => {
    FakeEventSource.latest().open();
  });
}

async function emit(frame: Record<string, unknown>) {
  await act(async () => {
    FakeEventSource.latest().emitNotification(frame);
  });
}

describe("<NotificationBell />", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.localStorage.setItem("mycelium.principal", "bob");
    resetStreamHub();
    FakeEventSource.reset();
    vi.stubGlobal("EventSource", FakeEventSource);
    ping.mockClear();
  });

  it("lists a message that mentions you, with who and where", async () => {
    const user = userEvent.setup();
    await start();
    await emit(message("hey @bob take a look"));

    await user.click(await screen.findByLabelText("1 unread mention"));
    expect(screen.getByText("alice")).toBeInTheDocument();
    expect(screen.getByText("sprint · channel")).toBeInTheDocument();
    expect(screen.getByText("hey @bob take a look")).toBeInTheDocument();
  });

  it("leaves out a message that doesn't mention you, and a silent mention", async () => {
    await start();
    await emit(message("hey @carol take a look"));
    await emit(message("done, for @~bob"));
    expect(screen.getByLabelText("Mentions")).toBeInTheDocument();
    expect(ping).not.toHaveBeenCalled();
  });

  it("plays a sound for a mention", async () => {
    await start();
    await emit(message("@bob can you check?"));
    expect(ping).toHaveBeenCalledTimes(1);
  });

  it("names the task of a mention in a thread and opens that thread", async () => {
    const user = userEvent.setup();
    await start();
    await emit(message("@bob which preset?", THREAD));

    await user.click(await screen.findByLabelText("1 unread mention"));
    expect(await screen.findByText("sprint · Zoom and pan images")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /which preset/ })).toHaveAttribute(
      "href",
      "/room/sprint?focus=episode%3At1",
    );
  });

  it("marking all read clears the count", async () => {
    const user = userEvent.setup();
    await start();
    await emit(message("hey @bob take a look"));

    await user.click(await screen.findByLabelText("1 unread mention"));
    const panel = (await screen.findByText("Mentions", { selector: "span" })).closest("[data-slot=popover-content]")!;
    await user.click(within(panel as HTMLElement).getByLabelText("Mark all read"));
    expect(screen.getByLabelText("Mentions", { selector: "button" })).toBeInTheDocument();
  });

  it("dismissing a mention removes it from the list", async () => {
    const user = userEvent.setup();
    await start();
    await emit(message("hey @bob take a look"));
    await user.click(await screen.findByLabelText("1 unread mention"));

    await user.click(screen.getByLabelText("Dismiss"));
    expect(screen.queryByText("hey @bob take a look")).not.toBeInTheDocument();
  });
});
