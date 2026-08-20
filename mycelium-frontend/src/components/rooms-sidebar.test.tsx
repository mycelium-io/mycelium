// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { act } from "react";
import { screen, within } from "@testing-library/react";
import { renderWithSWR } from "@/test/swr";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { FakeEventSource } from "@/test/fake-event-source";

const push = vi.fn();

vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

vi.mock("@/lib/api", () => ({
  fetchRooms: vi.fn(),
  getAppEventsSSEUrl: () => "/api/events/stream",
  getNotificationsSSEUrl: () => "/api/notifications/stream",
}));

import { CurrentUserProvider } from "@/components/current-user";
import { KeymapProvider } from "@/components/keymap-provider";
import { NotificationsProvider } from "@/components/notifications-provider";
import { RoomsSidebar } from "@/components/rooms-sidebar";
import { fetchRooms } from "@/lib/api";

function rooms(...names: string[]) {
  return names.map(name => ({ name }));
}

async function renderSidebar(names: string[], activeRoom: string | null = null) {
  vi.mocked(fetchRooms).mockResolvedValue(rooms(...names) as never);
  renderWithSWR(
    <CurrentUserProvider>
      <NotificationsProvider>
        <KeymapProvider>
          <RoomsSidebar activeRoom={activeRoom} />
        </KeymapProvider>
      </NotificationsProvider>
    </CurrentUserProvider>,
  );
  await act(async () => {});
  return userEvent.setup();
}

describe("<RoomsSidebar /> keyboard navigation", () => {
  beforeEach(() => {
    push.mockClear();
    FakeEventSource.reset();
    vi.stubGlobal("EventSource", FakeEventSource);
  });

  it("cycles to the next and previous room", async () => {
    const user = await renderSidebar(["alpha", "beta", "gamma"], "beta");

    await user.keyboard("]");
    expect(push).toHaveBeenLastCalledWith("/room/gamma");
    // "[[" is userEvent's escape for a literal "[".
    await user.keyboard("[[");
    expect(push).toHaveBeenLastCalledWith("/room/alpha");
  });

  it("wraps around the ends of the list", async () => {
    const user = await renderSidebar(["alpha", "beta"], "beta");

    await user.keyboard("]");
    expect(push).toHaveBeenLastCalledWith("/room/alpha");
  });

  it("badges the first nine rooms while the modifier is held, and jumps on the digit", async () => {
    const names = Array.from({ length: 11 }, (_, i) => `room-${i}`);
    const user = await renderSidebar(names);

    await user.keyboard("{Alt>}");
    const badges = [...document.querySelectorAll("nav [data-key-badge]")].map(el => el.textContent);
    expect(badges).toEqual(["1", "2", "3", "4", "5", "6", "7", "8", "9"]);
    // The brand wears its own key in the same hold.
    expect(document.querySelector("a[href='/'] [data-key-badge]")).toHaveTextContent("H");

    await user.keyboard("2{/Alt}");
    expect(push).toHaveBeenCalledWith("/room/room-1");
    expect(document.querySelector("[data-key-badge]")).toBeNull();
  });

  it("switches among the rooms the filter leaves on screen", async () => {
    const user = await renderSidebar(["alpha", "beta", "bravo"]);

    await user.click(screen.getByPlaceholderText("Filter rooms…"));
    await user.keyboard("b");
    // The filter box has focus, so the keybinds stay out of the way.
    expect(push).not.toHaveBeenCalled();

    await user.keyboard("{Escape}");
    await user.keyboard("{Alt>}2{/Alt}");
    expect(push).toHaveBeenCalledWith("/room/bravo");
  });
});

describe("<RoomsSidebar /> unread badges", () => {
  beforeEach(() => {
    FakeEventSource.reset();
    vi.stubGlobal("EventSource", FakeEventSource);
    window.localStorage.clear();
  });

  const seed = (list: { room: string; read: boolean }[]) =>
    window.localStorage.setItem("mycelium.notifications", JSON.stringify(list));

  it("badges a room that has unread activity, and leaves others clean", async () => {
    seed([
      { room: "beta", read: false },
      { room: "beta", read: false },
      { room: "alpha", read: true },
    ]);
    await renderSidebar(["alpha", "beta"]);

    const beta = screen.getByRole("link", { name: /beta/ });
    expect(within(beta).getByLabelText("2 unread")).toBeInTheDocument();
    const alpha = screen.getByRole("link", { name: /alpha/ });
    expect(within(alpha).queryByLabelText(/unread/)).toBeNull();
  });

  it("does not badge the room you're already viewing", async () => {
    seed([{ room: "beta", read: false }]);
    await renderSidebar(["alpha", "beta"], "beta");
    // Scoped to the row: beta's unread still counts globally (the footer bell),
    // it just shouldn't badge the room you're currently reading.
    const beta = screen.getByRole("link", { name: /beta/ });
    expect(within(beta).queryByLabelText(/unread/)).toBeNull();
  });

  it("does not badge a muted room, and marks it as muted", async () => {
    window.localStorage.setItem(
      "mycelium.notification-settings",
      JSON.stringify({ roomLevels: { beta: "muted" } }),
    );
    seed([{ room: "beta", read: false }]);
    await renderSidebar(["alpha", "beta"]);
    const beta = screen.getByRole("link", { name: /beta/ });
    expect(within(beta).queryByLabelText(/unread/)).toBeNull();
    expect(within(beta).getByLabelText("muted")).toBeInTheDocument();
  });
});
