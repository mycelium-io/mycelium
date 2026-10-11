// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { act } from "react";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeEventSource } from "@/test/fake-event-source";
import { resetStreamHub } from "@/lib/stream-hub";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/lib/api", () => ({
  fetchRoomAgents: vi.fn(async () => []),
  fetchMemories: vi.fn(async () => []),
}));

import { CurrentUserProvider } from "@/components/current-user";
import { NotificationsProvider } from "@/components/notifications-provider";
import { TaskToast, TOAST_MS } from "@/components/task-toast";

let seq = 0;

function ask(text: string, episode: string) {
  seq += 1;
  return {
    id: `msg-${seq}`,
    room_name: "sprint",
    sender_handle: "alice",
    message_type: "l9_exchange",
    created_at: `2026-10-11T10:${String(10 + seq).padStart(2, "0")}:00Z`,
    episode: `urn:ioc:mycelium:episode:sprint:${episode}`,
    content: JSON.stringify({ content: text }),
  };
}

async function start() {
  render(
    <CurrentUserProvider>
      <NotificationsProvider>
        <TaskToast />
      </NotificationsProvider>
    </CurrentUserProvider>,
  );
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

describe("<TaskToast />", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.localStorage.setItem("mycelium.principal", "bob");
    resetStreamHub();
    FakeEventSource.reset();
    vi.stubGlobal("EventSource", FakeEventSource);
    vi.spyOn(document, "hasFocus").mockReturnValue(true);
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("shows one toast when a task asks you, with one action", async () => {
    await start();
    await emit(ask("@bob which preset?", "t1"));
    const toast = await screen.findByRole("status");
    expect(toast).toHaveTextContent("Asks you");
    expect(toast).toHaveTextContent("alice: @bob which preset?");
    expect(screen.getByRole("link", { name: "Open" })).toHaveAttribute("href", "/room/sprint?focus=episode%3At1");
  });

  it("replaces the older toast with the newer one", async () => {
    await start();
    await emit(ask("@bob first?", "t1"));
    await emit(ask("@bob second?", "t2"));
    const toasts = screen.getAllByRole("status");
    expect(toasts).toHaveLength(1);
    expect(toasts[0]).toHaveTextContent("second?");
  });

  it("goes away on its own after a while", async () => {
    await start();
    vi.useFakeTimers();
    await emit(ask("@bob which preset?", "t1"));
    expect(screen.getByRole("status")).toBeInTheDocument();
    await act(async () => {
      vi.advanceTimersByTime(TOAST_MS + 100);
    });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("stays quiet when toasts are off", async () => {
    window.localStorage.setItem("mycelium.notification-settings", JSON.stringify({ toasts: "off" }));
    await start();
    await emit(ask("@bob which preset?", "t1"));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
