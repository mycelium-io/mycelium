// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { act } from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeEventSource } from "@/test/fake-event-source";
import { resetStreamHub } from "@/lib/stream-hub";

const THREAD = "urn:ioc:mycelium:episode:sprint:t1";
const NOTE_THREAD = "urn:ioc:mycelium:episode:sprint:n1";

/** What the hub's speech server was asked to say, and whether it has one. */
const spoken: string[] = [];
const voice = { speech: false };
vi.mock("@/lib/api", () => ({
  // Every memory in the room: a board row and a note, each with its thread.
  fetchMemories: vi.fn(async () => [
    { key: "work/zoom", value: { text: "Zoom and pan images\n\nbody" }, episode: THREAD },
    { key: "context/chat-buddy", value: "Talking with the chat buddy", episode: NOTE_THREAD },
  ]),
  fetchVoiceStatus: vi.fn(async () => ({ state: "ready", speech: voice.speech })),
  fetchSpeech: vi.fn(async (text: string) => {
    spoken.push(text);
    return new ArrayBuffer(8);
  }),
}));
const push = vi.fn();
const path = { current: "/" };
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }), usePathname: () => path.current }));
const ping = vi.fn();
/** Playing a sentence waits until the test ends it. */
const playing: (() => void)[] = [];
vi.mock("@/lib/audio-ping", () => ({
  ping: (...a: unknown[]) => ping(...a),
  primeAudio: () => {},
  audioReady: () => true,
  playAudio: () => new Promise<void>((resolve) => playing.push(resolve)),
}));

import { SWRConfig } from "swr";
import { CurrentUserProvider } from "@/components/current-user";
import { NotificationsProvider } from "@/components/notifications-provider";
import { NotificationBell } from "@/components/notification-bell";
import { OPEN_MENTION_EVENT } from "@/lib/notifications";

const CREATED = "2026-08-15T10:00:00.000000+00:00";
let seq = 0;

function renderBell() {
  // A cache of its own, so whether the hub has a speech server is asked again.
  return render(
    <SWRConfig value={{ provider: () => new Map() }}>
      <CurrentUserProvider>
        <NotificationsProvider>
          <NotificationBell />
        </NotificationsProvider>
      </CurrentUserProvider>
    </SWRConfig>,
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
    spoken.length = 0;
    playing.length = 0;
    voice.speech = false;
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

  it("names a note whose discussion mentions you, not only a task", async () => {
    const user = userEvent.setup();
    await start();
    await emit(message("@bob thoughts?", NOTE_THREAD));
    await user.click(await screen.findByLabelText("1 unread mention"));
    expect(await screen.findByText("sprint · Talking with the chat buddy")).toBeInTheDocument();
  });

  it("opens a mention when its system notification is clicked", async () => {
    await start();
    await act(async () => {
      window.dispatchEvent(new CustomEvent(OPEN_MENTION_EVENT, { detail: "/room/sprint?focus=episode%3At1" }));
    });
    expect(push).toHaveBeenCalledWith("/room/sprint?focus=episode%3At1");
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

  describe("read aloud", () => {
    function turnOn() {
      voice.speech = true;
      window.localStorage.setItem("mycelium.notification-settings", JSON.stringify({ readAloud: true }));
      vi.spyOn(document, "hasFocus").mockReturnValue(true);
      vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    }

    afterEach(() => {
      vi.restoreAllMocks();
      vi.unstubAllGlobals();
    });

    it("reads a mention aloud with its words on the bell, and stops on Esc", async () => {
      turnOn();
      const user = userEvent.setup();
      await start();
      await emit(message("@bob can you check? It's **slow** today.\n\nMore detail here."));

      const popover = await screen.findByRole("region", { name: "Reading aloud: alice" });
      expect(spoken[0]).toBe("alice, in sprint.");
      // The message as written, markup aside, and only its start until Read all.
      expect(within(popover).getByText("@bob can you check?")).toBeInTheDocument();
      expect(within(popover).getByText("It's slow today.")).toBeInTheDocument();
      expect(within(popover).getByRole("button", { name: "Read all" })).toBeInTheDocument();

      await user.keyboard("{Escape}");
      expect(screen.queryByRole("region", { name: /Reading aloud/ })).not.toBeInTheDocument();
    });

    it("lights the sentence being said", async () => {
      turnOn();
      await start();
      await emit(message("@bob first. Second."));
      const popover = await screen.findByRole("region", { name: "Reading aloud: alice" });
      await act(async () => playing.shift()?.());
      expect(within(popover).getByText("@bob first.")).toHaveAttribute("data-lit", "true");
      expect(within(popover).getByText("Second.")).not.toHaveAttribute("data-lit");
    });

    it("says nothing while it's off, or the hub has no speech server", async () => {
      vi.spyOn(document, "hasFocus").mockReturnValue(true);
      vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
      voice.speech = true;
      await start();
      await emit(message("@bob are you there?"));
      expect(spoken).toEqual([]);
      expect(screen.queryByRole("region", { name: /Reading aloud/ })).not.toBeInTheDocument();
    });

    it("says nothing from a hidden tab", async () => {
      turnOn();
      vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
      await start();
      await emit(message("@bob are you there?"));
      await act(async () => {});
      expect(spoken).toEqual([]);
    });

    it("announces who is being read, not the message the voice is saying", async () => {
      turnOn();
      await start();
      await emit(message("@bob can you check?"));
      const popover = await screen.findByRole("region", { name: "Reading aloud: alice" });
      const live = within(popover).getByRole("status");
      expect(live).toHaveTextContent("Reading a mention from alice");
      expect(live).not.toHaveTextContent("check");
    });

    it("leaves Esc to an open dialog", async () => {
      turnOn();
      const user = userEvent.setup();
      await start();
      await emit(message("@bob can you check?"));
      await screen.findByRole("region", { name: "Reading aloud: alice" });
      const dialog = document.body.appendChild(document.createElement("div"));
      dialog.setAttribute("role", "dialog");
      await user.keyboard("{Escape}");
      expect(screen.getByRole("region", { name: "Reading aloud: alice" })).toBeInTheDocument();
      dialog.remove();
    });

    it("doesn't read a mention in the room another focused window shows", async () => {
      turnOn();
      // This window is beside the one being worked in, and agrees with the
      // other windows through Web Locks (which jsdom doesn't have).
      vi.spyOn(document, "hasFocus").mockReturnValue(false);
      const held = new Set<string>();
      vi.stubGlobal("navigator", {
        ...navigator,
        locks: {
          request: async (name: string, _opts: unknown, cb: (lock: unknown) => Promise<unknown>) => {
            if (held.has(name)) return cb(null);
            held.add(name);
            return cb({ name });
          },
        },
      });
      await start();
      const other = new BroadcastChannel("mycelium-notifications");
      other.postMessage({ type: "viewing", room: "sprint" });
      await act(async () => new Promise((r) => setTimeout(r, 20)));
      await emit(message("@bob in the room you're looking at"));
      await act(async () => new Promise((r) => setTimeout(r, 400)));
      expect(spoken).toEqual([]);
      // Once that window shows something else, this one reads it.
      other.postMessage({ type: "viewing", room: null });
      await act(async () => new Promise((r) => setTimeout(r, 20)));
      await emit(message("@bob now it's yours"));
      await screen.findByRole("region", { name: "Reading aloud: alice" }, { timeout: 2000 });
      other.close();
    });

    it("tells the other windows when the focused one leaves a room for another page", async () => {
      vi.spyOn(document, "hasFocus").mockReturnValue(true);
      const heard: unknown[] = [];
      const other = new BroadcastChannel("mycelium-notifications");
      other.onmessage = (e) => heard.push(e.data);
      path.current = "/room/sprint";
      const { rerender } = renderBell();
      await act(async () => new Promise((r) => setTimeout(r, 20)));
      path.current = "/settings/notifications";
      rerender(
        <SWRConfig value={{ provider: () => new Map() }}>
          <CurrentUserProvider>
            <NotificationsProvider>
              <NotificationBell />
            </NotificationsProvider>
          </CurrentUserProvider>
        </SWRConfig>,
      );
      await act(async () => new Promise((r) => setTimeout(r, 20)));
      expect(heard).toContainEqual({ type: "viewing", room: "sprint" });
      expect(heard.at(-1)).toEqual({ type: "viewing", room: null });
      other.close();
      path.current = "/";
    });

    it("keeps the whole message out of what the bell stores", async () => {
      turnOn();
      await start();
      const long = `@bob ${"word ".repeat(60)}end.`;
      await emit(message(long));
      await screen.findByRole("region", { name: "Reading aloud: alice" });
      const stored = window.localStorage.getItem("mycelium.notifications") ?? "";
      expect(stored).not.toContain("end.");
      expect(stored).not.toContain('"text"');
    });
  });
});
