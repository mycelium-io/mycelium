// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { act } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { FakeEventSource } from "@/test/fake-event-source";
import { renderWithProviders } from "@/test/render-with-providers";

vi.mock("@/lib/api", () => ({
  getSSEUrl: (room: string) => `/api/rooms/${room}/messages/stream`,
  fetchMessages: vi.fn().mockResolvedValue({ messages: [] }),
  fetchRoomAgents: vi.fn().mockResolvedValue([]),
  fetchPendingInvites: vi.fn().mockResolvedValue([]),
  respondToInvite: vi.fn(),
  logFetchError: () => () => undefined,
}));

vi.mock("@/lib/audio-ping", () => ({
  playPing: vi.fn(),
  primeAudio: vi.fn(),
  PING_SOUNDS: ["chime", "ping", "tone"],
}));

import { EventStream } from "@/components/event-stream";
import { playPing } from "@/lib/audio-ping";

const CREATED = "2026-08-04T10:00:00.000000+00:00";

function broadcast(text: string, sender = "alice", recipient: string | null = null) {
  return {
    message_type: recipient ? "direct" : "broadcast",
    sender_handle: sender,
    recipient_handle: recipient,
    created_at: CREATED,
    content: text,
  };
}

function consensus() {
  return {
    message_type: "coordination_consensus",
    sender_handle: "system",
    created_at: CREATED,
    content: JSON.stringify({ plan: "agreed", assignments: { a: "b" } }),
  };
}

function setHidden(hidden: boolean) {
  Object.defineProperty(document, "hidden", { value: hidden, configurable: true });
}

function setNotifySettings(overrides: Record<string, unknown>) {
  window.localStorage.setItem(
    "mycelium.notify",
    JSON.stringify({ enabled: true, scope: "all", sound: "chime", volume: 0.5, ...overrides }),
  );
}

describe("<EventStream /> audio ping", () => {
  beforeEach(() => {
    FakeEventSource.reset();
    vi.stubGlobal("EventSource", FakeEventSource);
    vi.mocked(playPing).mockClear();
    window.localStorage.clear();
    setHidden(false);
  });

  it("never pings while the tab is visible", async () => {
    setNotifySettings({});
    renderWithProviders(<EventStream roomName="sprint" />);
    await act(async () => {});
    const es = FakeEventSource.latest();

    await act(async () => {
      es.open();
      es.emit(broadcast("hello"));
    });

    expect(playPing).not.toHaveBeenCalled();
  });

  it("does not ping when the toggle is off, even while hidden", async () => {
    setNotifySettings({ enabled: false });
    renderWithProviders(<EventStream roomName="sprint" />);
    await act(async () => {});
    const es = FakeEventSource.latest();
    setHidden(true);

    await act(async () => {
      es.open();
      es.emit(broadcast("hello"));
    });

    expect(playPing).not.toHaveBeenCalled();
  });

  it("pings on a broadcast while hidden with scope 'all'", async () => {
    setNotifySettings({ scope: "all", sound: "chime", volume: 0.5 });
    renderWithProviders(<EventStream roomName="sprint" />);
    await act(async () => {});
    const es = FakeEventSource.latest();
    setHidden(true);

    await act(async () => {
      es.open();
      es.emit(broadcast("hello everyone"));
    });

    expect(playPing).toHaveBeenCalledWith("chime", 0.5);
  });

  it("scope 'needs-me' ignores chat that doesn't mention me", async () => {
    window.localStorage.setItem("mycelium.principal", "julia");
    setNotifySettings({ scope: "needs-me" });
    renderWithProviders(<EventStream roomName="sprint" />);
    await act(async () => {});
    const es = FakeEventSource.latest();
    setHidden(true);

    await act(async () => {
      es.open();
      es.emit(broadcast("just chatting about the plan"));
    });

    expect(playPing).not.toHaveBeenCalled();
  });

  it("scope 'needs-me' pings on an @-mention of my acting-as handle", async () => {
    window.localStorage.setItem("mycelium.principal", "julia");
    setNotifySettings({ scope: "needs-me", sound: "ping", volume: 0.8 });
    renderWithProviders(<EventStream roomName="sprint" />);
    await act(async () => {});
    const es = FakeEventSource.latest();
    setHidden(true);

    await act(async () => {
      es.open();
      es.emit(broadcast("@julia can you take a look?"));
    });

    expect(playPing).toHaveBeenCalledWith("ping", 0.8);
  });

  it("scope 'needs-me' always pings on consensus", async () => {
    setNotifySettings({ scope: "needs-me", sound: "tone" });
    renderWithProviders(<EventStream roomName="sprint" />);
    await act(async () => {});
    const es = FakeEventSource.latest();
    setHidden(true);

    await act(async () => {
      es.open();
      es.emit(consensus());
    });

    expect(playPing).toHaveBeenCalledWith("tone", 0.5);
  });

  it("debounces a burst of activity into a single ping", async () => {
    setNotifySettings({ scope: "all" });
    renderWithProviders(<EventStream roomName="sprint" />);
    await act(async () => {});
    const es = FakeEventSource.latest();
    setHidden(true);

    await act(async () => {
      es.open();
      es.emit(broadcast("one"));
      es.emit(broadcast("two"));
      es.emit(broadcast("three"));
    });

    expect(playPing).toHaveBeenCalledTimes(1);
  });
});
