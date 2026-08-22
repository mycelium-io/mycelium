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
  useRoomStream,
  useStreamConnected,
} from "@/lib/stream-hub";

/** Connections opened and not since closed — the number the browser's ~6-per-
 *  origin cap is actually spent on. */
function live(): FakeEventSource[] {
  return FakeEventSource.instances.filter((es) => !es.closed);
}

function RoomFeed({ room, onFrame }: { room: string; onFrame: (d: unknown) => void }) {
  useRoomStream(room, onFrame);
  return null;
}

function AppFeed({ onFrame }: { onFrame: (d: unknown) => void }) {
  useAppStream(onFrame);
  return null;
}

function Notifications({ onFrame }: { onFrame: (d: unknown) => void }) {
  useNotificationStream(onFrame);
  return null;
}

function Badge() {
  return <span data-testid="badge">{useStreamConnected() ? "live" : "reconnecting"}</span>;
}

describe("stream hub", () => {
  beforeEach(() => {
    resetStreamHub();
    FakeEventSource.reset();
    vi.stubGlobal("EventSource", FakeEventSource);
  });

  it("holds one connection for every consumer on the page", () => {
    const noop = () => {};
    render(
      <>
        <RoomFeed room="sprint" onFrame={noop} />
        <RoomFeed room="sprint" onFrame={noop} />
        <AppFeed onFrame={noop} />
        <Notifications onFrame={noop} />
        <Badge />
      </>,
    );

    // Four feeds — the room channel, the L9 inspector's view of it, app events
    // and notifications — on one connection, carrying the room in its URL.
    expect(live()).toHaveLength(1);
    expect(live()[0].url).toBe("/api/stream?room=sprint");
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
    const es = FakeEventSource.latest();

    act(() => {
      es.emit({ id: "m1" });
      es.emitApp({ type: "room_created" });
      es.emitNotification({ id: "n1" });
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
    const es = FakeEventSource.latest();
    expect(es.url).toBe("/api/stream?room=atlas&room=sprint");

    act(() => es.emitChannel("room", { id: "m1" }, "atlas"));

    expect(atlas).toHaveBeenCalledExactlyOnceWith({ id: "m1" });
    expect(sprint).not.toHaveBeenCalled();
  });

  it("reconnects against the new room when the open room changes", () => {
    const { rerender } = render(<RoomFeed room="sprint" onFrame={() => {}} />);
    expect(FakeEventSource.latest().url).toBe("/api/stream?room=sprint");

    rerender(<RoomFeed room="atlas" onFrame={() => {}} />);

    expect(live()).toHaveLength(1);
    expect(live()[0].url).toBe("/api/stream?room=atlas");
  });

  it("keeps the connection when a second consumer of the same room mounts", () => {
    const { rerender } = render(<RoomFeed room="sprint" onFrame={() => {}} />);
    const first = FakeEventSource.latest();

    rerender(
      <>
        <RoomFeed room="sprint" onFrame={() => {}} />
        <RoomFeed room="sprint" onFrame={() => {}} />
      </>,
    );

    expect(FakeEventSource.instances).toHaveLength(1);
    expect(first.closed).toBe(false);
  });

  it("re-renders a consumer's latest handler without touching the connection", () => {
    const first = vi.fn();
    const second = vi.fn();
    const { rerender } = render(<RoomFeed room="sprint" onFrame={first} />);
    const es = FakeEventSource.latest();

    rerender(<RoomFeed room="sprint" onFrame={second} />);
    act(() => es.emit({ id: "m1" }));

    expect(FakeEventSource.instances).toHaveLength(1);
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledExactlyOnceWith({ id: "m1" });
  });

  it("closes the connection once the last consumer unmounts", () => {
    const { unmount } = render(<RoomFeed room="sprint" onFrame={() => {}} />);
    const es = FakeEventSource.latest();

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

    act(() => FakeEventSource.latest().emit({ id: "m1" }));

    expect(gone).not.toHaveBeenCalled();
    expect(stays).toHaveBeenCalledOnce();
  });

  it("reports one connection state to every indicator", () => {
    const { getByTestId } = render(
      <>
        <RoomFeed room="sprint" onFrame={() => {}} />
        <Badge />
      </>,
    );
    expect(getByTestId("badge")).toHaveTextContent("reconnecting");

    act(() => FakeEventSource.latest().open());
    expect(getByTestId("badge")).toHaveTextContent("live");
  });

  it("goes live on the multiplexer's ready frame, before any upstream speaks", () => {
    const { getByTestId } = render(
      <>
        <RoomFeed room="sprint" onFrame={() => {}} />
        <Badge />
      </>,
    );

    act(() => FakeEventSource.latest().emitRaw("ready", JSON.stringify({ rooms: ["sprint"] })));

    expect(getByTestId("badge")).toHaveTextContent("live");
  });

  it("redials after a drop, and reports reconnecting in between", () => {
    vi.useFakeTimers();
    try {
      const { getByTestId } = render(
        <>
          <RoomFeed room="sprint" onFrame={() => {}} />
          <Badge />
        </>,
      );
      const es = FakeEventSource.latest();
      act(() => es.open());

      act(() => es.onerror?.());
      expect(getByTestId("badge")).toHaveTextContent("reconnecting");
      expect(live()).toHaveLength(0);

      act(() => void vi.advanceTimersByTime(5000));
      expect(live()).toHaveLength(1);
      expect(live()[0].url).toBe("/api/stream?room=sprint");
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not redial once the last consumer is gone", () => {
    vi.useFakeTimers();
    try {
      const { unmount } = render(<RoomFeed room="sprint" onFrame={() => {}} />);
      act(() => FakeEventSource.latest().onerror?.());
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

    act(() => FakeEventSource.latest().emit({ id: "m1" }));

    expect(thrower).toHaveBeenCalledOnce();
    expect(other).toHaveBeenCalledExactlyOnceWith({ id: "m1" });
  });

  it("drops a malformed frame without disturbing the connection", () => {
    const room = vi.fn();
    render(<RoomFeed room="sprint" onFrame={room} />);
    const es = FakeEventSource.latest();

    act(() => {
      es.emitRaw("room", "not json");
      es.emit({ id: "m1" });
    });

    expect(room).toHaveBeenCalledExactlyOnceWith({ id: "m1" });
    expect(es.closed).toBe(false);
  });
});
