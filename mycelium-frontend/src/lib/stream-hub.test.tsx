// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { act } from "react";
import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { FakeEventSource } from "@/test/fake-event-source";
import {
  resetStreamHub,
  useAppStream,
  useNotificationStream,
  useNotificationsConnected,
  useRoomConnected,
  useRoomStream,
} from "@/lib/stream-hub";

/** Connections opened and not since closed — the number the browser's ~6-per-
 *  origin cap is actually spent on. */
function live(): FakeEventSource[] {
  return FakeEventSource.instances.filter((es) => !es.closed);
}

function liveUrls(): string[] {
  return live().map((es) => es.url).sort();
}

/** The one connection carrying a room, for tests that drive room traffic. */
function roomConnection(): FakeEventSource {
  const found = live().find((es) => es.url.includes("room="));
  if (!found) throw new Error("no room connection is open");
  return found;
}

function globalConnection(): FakeEventSource {
  const found = live().find((es) => !es.url.includes("room="));
  if (!found) throw new Error("no global connection is open");
  return found;
}

const noop = () => {};

function RoomFeed({ room, onFrame = noop }: { room: string; onFrame?: (d: unknown) => void }) {
  useRoomStream(room, onFrame);
  return null;
}

function AppFeed({ onFrame = noop }: { onFrame?: (d: unknown) => void }) {
  useAppStream(onFrame);
  return null;
}

function Notifications({ onFrame = noop }: { onFrame?: (d: unknown) => void }) {
  useNotificationStream(onFrame);
  return null;
}

function RoomBadge({ room }: { room: string }) {
  return <span data-testid="badge">{useRoomConnected(room) ? "live" : "reconnecting"}</span>;
}

function NotificationsBadge() {
  return (
    <span data-testid="notif-badge">{useNotificationsConnected() ? "live" : "reconnecting"}</span>
  );
}

/** The app's steady state: notifications mounted in the root layout, a room
 *  open beneath it. */
function Shell({ room }: { room: string | null }) {
  return (
    <>
      <Notifications />
      <AppFeed />
      {room ? <RoomFeed room={room} /> : null}
    </>
  );
}

describe("stream hub", () => {
  beforeEach(() => {
    resetStreamHub();
    FakeEventSource.reset();
    vi.stubGlobal("EventSource", FakeEventSource);
  });

  it("holds two connections for every consumer on the page", () => {
    render(
      <>
        <RoomFeed room="sprint" />
        <RoomFeed room="sprint" />
        <AppFeed />
        <Notifications />
      </>,
    );

    // Four feeds — the room channel, the L9 inspector's view of it, app events
    // and notifications — on two connections: the globals, and the open room.
    expect(liveUrls()).toEqual(["/api/stream", "/api/stream?room=sprint"]);
  });

  it("routes each channel to the consumers that asked for it", () => {
    const room = vi.fn();
    const app = vi.fn();
    const notification = vi.fn();
    render(
      <>
        <RoomFeed room="sprint" onFrame={room} />
        <AppFeed onFrame={app} />
        <Notifications onFrame={notification} />
      </>,
    );

    act(() => {
      roomConnection().emit({ id: "m1" });
      globalConnection().emitApp({ type: "room_created" });
      globalConnection().emitNotification({ id: "n1" });
    });

    expect(room).toHaveBeenCalledExactlyOnceWith({ id: "m1" });
    expect(app).toHaveBeenCalledExactlyOnceWith({ type: "room_created" });
    expect(notification).toHaveBeenCalledExactlyOnceWith({ id: "n1" });
  });

  it("delivers a room frame only to subscribers of that room", () => {
    const sprint = vi.fn();
    const atlas = vi.fn();
    render(
      <>
        <RoomFeed room="sprint" onFrame={sprint} />
        <RoomFeed room="atlas" onFrame={atlas} />
      </>,
    );
    const es = roomConnection();
    expect(es.url).toBe("/api/stream?room=atlas&room=sprint");

    act(() => es.emitChannel("room", { id: "m1" }, "atlas"));

    expect(atlas).toHaveBeenCalledExactlyOnceWith({ id: "m1" });
    expect(sprint).not.toHaveBeenCalled();
  });

  // The notification feed has no replay, so a re-dial loses whatever was
  // published while it was down. Navigation must not touch it.
  it("leaves the global connection untouched when the open room changes", () => {
    const { rerender } = render(<Shell room="sprint" />);
    const globals = globalConnection();

    rerender(<Shell room="atlas" />);

    expect(globals.closed).toBe(false);
    expect(globalConnection()).toBe(globals);
    expect(liveUrls()).toEqual(["/api/stream", "/api/stream?room=atlas"]);
  });

  it("dials the room connection exactly once across a navigation", () => {
    const { rerender } = render(<Shell room="sprint" />);
    const before = FakeEventSource.instances.length;

    rerender(<Shell room="atlas" />);

    // One new connection — the room's. No intermediate roomless re-dial.
    expect(FakeEventSource.instances.length).toBe(before + 1);
    expect(FakeEventSource.latest().url).toBe("/api/stream?room=atlas");
  });

  it("keeps a notification arriving mid-navigation", () => {
    const notification = vi.fn();
    const { rerender } = render(
      <>
        <Notifications onFrame={notification} />
        <RoomFeed room="sprint" />
      </>,
    );
    const globals = globalConnection();

    rerender(
      <>
        <Notifications onFrame={notification} />
        <RoomFeed room="atlas" />
      </>,
    );
    act(() => globals.emitNotification({ id: "n1" }));

    expect(notification).toHaveBeenCalledExactlyOnceWith({ id: "n1" });
  });

  it("keeps the connection when a second consumer of the same room mounts", () => {
    const { rerender } = render(<RoomFeed room="sprint" />);
    const first = roomConnection();

    rerender(
      <>
        <RoomFeed room="sprint" />
        <RoomFeed room="sprint" />
      </>,
    );

    expect(FakeEventSource.instances).toHaveLength(1);
    expect(first.closed).toBe(false);
  });

  it("re-renders a consumer's latest handler without touching the connection", () => {
    const first = vi.fn();
    const second = vi.fn();
    const { rerender } = render(<RoomFeed room="sprint" onFrame={first} />);

    rerender(<RoomFeed room="sprint" onFrame={second} />);
    act(() => roomConnection().emit({ id: "m1" }));

    expect(FakeEventSource.instances).toHaveLength(1);
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledExactlyOnceWith({ id: "m1" });
  });

  it("closes the connection once the last consumer unmounts", () => {
    const { unmount } = render(<RoomFeed room="sprint" />);
    const es = roomConnection();

    unmount();

    expect(es.closed).toBe(true);
    expect(live()).toHaveLength(0);
  });

  it("stops delivering to a consumer that has unmounted", () => {
    const gone = vi.fn();
    const stays = vi.fn();
    const { rerender } = render(
      <>
        <RoomFeed room="sprint" onFrame={gone} />
        <RoomFeed room="sprint" onFrame={stays} />
      </>,
    );
    rerender(<RoomFeed room="sprint" onFrame={stays} />);

    act(() => roomConnection().emit({ id: "m1" }));

    expect(gone).not.toHaveBeenCalled();
    expect(stays).toHaveBeenCalledOnce();
  });

  describe("health", () => {
    // The multiplexer answers even when the backend behind it does not, so an
    // open socket is not evidence that anything is being delivered.
    it("stays reconnecting while the connection is open but the feed is down", () => {
      const { getByTestId } = render(
        <>
          <RoomFeed room="sprint" />
          <RoomBadge room="sprint" />
        </>,
      );

      act(() => roomConnection().open());
      expect(getByTestId("badge")).toHaveTextContent("reconnecting");

      act(() => roomConnection().emitStatus("room", false, "sprint"));
      expect(getByTestId("badge")).toHaveTextContent("reconnecting");
    });

    it("goes live when the server reports the feed delivering", () => {
      const { getByTestId } = render(
        <>
          <RoomFeed room="sprint" />
          <RoomBadge room="sprint" />
        </>,
      );

      act(() => roomConnection().goLive());

      expect(getByTestId("badge")).toHaveTextContent("live");
    });

    it("reports each feed's own health, not one shared verdict", () => {
      const { getByTestId } = render(
        <>
          <Shell room="sprint" />
          <RoomBadge room="sprint" />
          <NotificationsBadge />
        </>,
      );

      act(() => roomConnection().goLive());

      // The room is delivering; the global feeds have said nothing yet.
      expect(getByTestId("badge")).toHaveTextContent("live");
      expect(getByTestId("notif-badge")).toHaveTextContent("reconnecting");

      act(() => globalConnection().goLive());
      expect(getByTestId("notif-badge")).toHaveTextContent("live");
    });

    it("drops a feed's health when its connection goes", () => {
      const { getByTestId } = render(
        <>
          <RoomFeed room="sprint" />
          <RoomBadge room="sprint" />
        </>,
      );
      act(() => roomConnection().goLive());
      expect(getByTestId("badge")).toHaveTextContent("live");

      act(() => FakeEventSource.latest().onerror?.());

      expect(getByTestId("badge")).toHaveTextContent("reconnecting");
    });

    it("does not report health for a room the connection isn't carrying", () => {
      const { getByTestId } = render(
        <>
          <RoomFeed room="sprint" />
          <RoomBadge room="atlas" />
        </>,
      );

      act(() => roomConnection().goLive());

      expect(getByTestId("badge")).toHaveTextContent("reconnecting");
    });
  });

  it("redials after a drop", () => {
    vi.useFakeTimers();
    try {
      render(<RoomFeed room="sprint" />);
      const es = roomConnection();

      act(() => es.onerror?.());
      expect(live()).toHaveLength(0);

      act(() => void vi.advanceTimersByTime(5000));
      expect(liveUrls()).toEqual(["/api/stream?room=sprint"]);
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not redial once the last consumer is gone", () => {
    vi.useFakeTimers();
    try {
      const { unmount } = render(<RoomFeed room="sprint" />);
      act(() => roomConnection().onerror?.());
      unmount();

      act(() => void vi.advanceTimersByTime(5000));

      expect(live()).toHaveLength(0);
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps delivering to other consumers when one throws", () => {
    const thrower = vi.fn(() => {
      throw new Error("bad frame");
    });
    const other = vi.fn();
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <>
        <RoomFeed room="sprint" onFrame={thrower} />
        <RoomFeed room="sprint" onFrame={other} />
      </>,
    );

    act(() => roomConnection().emit({ id: "m1" }));

    expect(thrower).toHaveBeenCalledOnce();
    expect(other).toHaveBeenCalledExactlyOnceWith({ id: "m1" });
  });

  it("drops a malformed frame without disturbing the connection", () => {
    const room = vi.fn();
    render(<RoomFeed room="sprint" onFrame={room} />);
    const es = roomConnection();

    act(() => {
      es.emitRaw("room", "not json");
      es.emitRaw("status", "not json");
      es.emit({ id: "m1" });
    });

    expect(room).toHaveBeenCalledExactlyOnceWith({ id: "m1" });
    expect(es.closed).toBe(false);
  });
});
