// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { act } from "react";
import { render, screen, within } from "@testing-library/react";
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
  render(
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
  // The hint overlay tells a tap from a hold by wall clock, so the tests drive
  // it: unchanged means "tapped" (latched open), advanced means "held".
  let now = 0;

  beforeEach(() => {
    push.mockClear();
    now = 1_000;
    vi.spyOn(Date, "now").mockImplementation(() => now);
    FakeEventSource.reset();
    vi.stubGlobal("EventSource", FakeEventSource);
  });

  it("reveals a hint label per room and jumps to the one pressed", async () => {
    const user = await renderSidebar(["alpha", "beta", "gamma"]);

    await user.keyboard("{f>}");
    expect(screen.getByText("Press a hint label to jump")).toBeInTheDocument();
    expect(document.querySelectorAll("[data-hint]")).toHaveLength(3);

    await user.keyboard("d{/f}");
    expect(push).toHaveBeenCalledWith("/room/gamma");
    expect(screen.queryByText("Press a hint label to jump")).not.toBeInTheDocument();
  });

  it("expands to 2-char labels once the rooms outgrow the home row", async () => {
    const names = Array.from({ length: 12 }, (_, i) => `room-${i}`);
    const user = await renderSidebar(names);

    await user.keyboard("{f>}{/f}");
    const labels = [...document.querySelectorAll("[data-hint]")].map(el => el.getAttribute("data-hint"));
    expect(labels).toHaveLength(12);
    expect(labels.every(l => l?.length === 2)).toBe(true);

    // A partial label narrows without jumping; the second char commits.
    await user.keyboard("a");
    expect(push).not.toHaveBeenCalled();
    await user.keyboard("d");
    expect(push).toHaveBeenCalledWith("/room/room-2");
  });

  it("holds to peek: releasing the hint key closes an untouched overlay", async () => {
    const user = await renderSidebar(["alpha", "beta"]);

    await user.keyboard("{f>}");
    expect(document.querySelectorAll("[data-hint]")).toHaveLength(2);
    now += 400;
    await user.keyboard("{/f}");
    expect(document.querySelectorAll("[data-hint]")).toHaveLength(0);
    expect(push).not.toHaveBeenCalled();
  });

  it("escapes hint mode without navigating", async () => {
    const user = await renderSidebar(["alpha", "beta"]);

    await user.keyboard("{f>}{/f}");
    await user.keyboard("{Escape}");
    expect(document.querySelectorAll("[data-hint]")).toHaveLength(0);
    expect(push).not.toHaveBeenCalled();
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
    // Nine digits don't cover eleven rooms, so the overlay says where the rest are.
    expect(screen.getByText(/to label them all/)).toBeInTheDocument();

    await user.keyboard("2{/Alt}");
    expect(push).toHaveBeenCalledWith("/room/room-1");
    expect(document.querySelector("[data-key-badge]")).toBeNull();
    expect(screen.queryByText(/to label them all/)).not.toBeInTheDocument();
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
