// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { act, type ComponentProps } from "react";
import { screen, within } from "@testing-library/react";
import { renderWithSWR } from "@/test/swr";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { FakeEventSource } from "@/test/fake-event-source";
import { resetStreamHub } from "@/lib/stream-hub";

const push = vi.fn();

vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

vi.mock("@/lib/api", () => ({
  createRoom: vi.fn(),
  deleteRoom: vi.fn(),
  fetchRooms: vi.fn(),
}));

import { AuthSessionProvider } from "@/components/auth-session";
import { CurrentUserProvider } from "@/components/current-user";
import { InstallModalProvider } from "@/components/install-modal";
import { KeymapProvider } from "@/components/keymap-provider";
import { NotificationsProvider } from "@/components/notifications-provider";
import { RoomsSidebar } from "@/components/rooms-sidebar";
import { createRoom, deleteRoom, fetchRooms } from "@/lib/api";

type RoomArg = string | { name: string; is_public?: boolean; last_activity?: string };

function rooms(...names: RoomArg[]) {
  return names.map(r => (typeof r === "string" ? { name: r } : r));
}

async function renderSidebar(
  names: RoomArg[],
  activeRoom: string | null = null,
  props: Partial<ComponentProps<typeof RoomsSidebar>> = {},
) {
  vi.mocked(fetchRooms).mockResolvedValue(rooms(...names) as never);
  renderWithSWR(
    <CurrentUserProvider>
      <AuthSessionProvider>
        <NotificationsProvider>
          <KeymapProvider>
            <InstallModalProvider>
              <RoomsSidebar activeRoom={activeRoom} {...props} />
            </InstallModalProvider>
          </KeymapProvider>
        </NotificationsProvider>
      </AuthSessionProvider>
    </CurrentUserProvider>,
  );
  await act(async () => {});
  return userEvent.setup();
}

describe("<RoomsSidebar /> keyboard navigation", () => {
  beforeEach(() => {
    push.mockClear();
    resetStreamHub();
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
    push.mockClear();
    resetStreamHub();
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

describe("<RoomsSidebar /> collapsed strip", () => {
  beforeEach(() => {
    resetStreamHub();
    FakeEventSource.reset();
    vi.stubGlobal("EventSource", FakeEventSource);
    window.localStorage.clear();
  });

  it("keeps every room reachable as a monogram, without the filter", async () => {
    await renderSidebar(["alpha", "beta"], "beta", { collapsed: true });

    // Named for the screen reader, drawn as initials — still one click away.
    expect(screen.getByRole("link", { name: "alpha" })).toHaveAttribute("href", "/room/alpha");
    expect(screen.getByRole("link", { name: "beta" })).toHaveAttribute("href", "/room/beta");
    expect(screen.getByText("AL")).toBeInTheDocument();
    expect(screen.queryByPlaceholderText("Filter rooms…")).toBeNull();
  });

  it("still badges unread activity, and offers the way back", async () => {
    window.localStorage.setItem(
      "mycelium.notifications",
      JSON.stringify([{ room: "alpha", read: false }]),
    );
    const onCollapsedChange = vi.fn();
    const user = await renderSidebar(["alpha", "beta"], "beta", {
      collapsed: true,
      onCollapsedChange,
    });

    const alpha = screen.getByRole("link", { name: /alpha/ });
    expect(within(alpha).getByLabelText("1 unread")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Expand the rooms rail/ }));
    expect(onCollapsedChange).toHaveBeenCalledWith(false);
  });
});

describe("<RoomsSidebar /> room deletion", () => {
  beforeEach(() => {
    push.mockClear();
    resetStreamHub();
    FakeEventSource.reset();
    vi.stubGlobal("EventSource", FakeEventSource);
    vi.mocked(deleteRoom).mockResolvedValue(undefined);
  });

  it("requires confirmation before deleting a room", async () => {
    const user = await renderSidebar(["design review"]);

    await user.click(screen.getByRole("button", { name: "Delete room design review" }));
    expect(screen.getByRole("heading", { name: "Delete “design review”?" })).toBeInTheDocument();
    expect(deleteRoom).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(deleteRoom).not.toHaveBeenCalled();
  });

  it("deletes an inactive room without navigating", async () => {
    const user = await renderSidebar(["design review"], null);

    await user.click(screen.getByRole("button", { name: "Delete room design review" }));
    await user.click(screen.getByRole("button", { name: "Delete room" }));

    expect(deleteRoom).toHaveBeenCalledWith("design review");
    expect(push).not.toHaveBeenCalled();
  });

  it("returns home after deleting the active room", async () => {
    const user = await renderSidebar(["design review"], "design review");

    await user.click(screen.getByRole("button", { name: "Delete room design review" }));
    await user.click(screen.getByRole("button", { name: "Delete room" }));

    expect(push).toHaveBeenCalledWith("/");
  });
});

describe("<RoomsSidebar /> new room in the list", () => {
  beforeEach(() => {
    push.mockClear();
    vi.mocked(createRoom).mockReset();
    resetStreamHub();
    FakeEventSource.reset();
    vi.stubGlobal("EventSource", FakeEventSource);
  });

  it("types the name where the room will appear, then opens it", async () => {
    vi.mocked(createRoom).mockResolvedValue({} as never);
    const user = await renderSidebar(["alpha"]);

    await user.click(screen.getByRole("button", { name: "New room" }));
    await user.keyboard("design-review{Enter}");

    expect(createRoom).toHaveBeenCalledWith({
      name: "design-review",
      is_persistent: true,
      private: false,
      owner: "",
    });
    expect(push).toHaveBeenCalledWith("/room/design-review");
    expect(screen.queryByRole("textbox", { name: "New room name" })).not.toBeInTheDocument();
  });

  it("keeps the name and says why when the hub refuses it", async () => {
    vi.mocked(createRoom).mockRejectedValue(new Error("Room already exists"));
    const user = await renderSidebar(["alpha"]);

    await user.click(screen.getByRole("button", { name: "New room" }));
    await user.keyboard("alpha{Enter}");

    expect(await screen.findByRole("alert")).toHaveTextContent("Room already exists");
    expect(screen.getByRole("textbox", { name: "New room name" })).toHaveValue("alpha");
  });

  it("leaves on Esc without creating anything", async () => {
    const user = await renderSidebar(["alpha"]);

    await user.click(screen.getByRole("button", { name: "New room" }));
    await user.keyboard("half{Escape}");

    expect(createRoom).not.toHaveBeenCalled();
    expect(screen.queryByRole("textbox", { name: "New room name" })).not.toBeInTheDocument();
  });
});

describe("<RoomsSidebar /> private rooms", () => {
  const scratch = { name: "scratch", is_public: false, last_activity: "2026-09-02" };

  beforeEach(() => {
    push.mockClear();
    vi.mocked(createRoom).mockReset();
    resetStreamHub();
    FakeEventSource.reset();
    vi.stubGlobal("EventSource", FakeEventSource);
  });

  it("offers no filter until there is a private room", async () => {
    await renderSidebar(["alpha", "beta"]);
    expect(screen.queryByRole("radiogroup", { name: "Show rooms" })).not.toBeInTheDocument();
  });

  it("draws private rooms under their own heading, after the shared ones", async () => {
    // The private room is the most recent, and still comes after the shared.
    const user = await renderSidebar(["alpha", scratch], "alpha");
    const links = screen.getAllByRole("link").map(l => l.textContent);
    expect(links[0]).toContain("alpha");
    expect(links[1]).toContain("scratch");
    expect(screen.getByText("Private", { selector: "div" })).toBeInTheDocument();

    // Next/prev follows the list as drawn.
    await user.keyboard("]");
    expect(push).toHaveBeenLastCalledWith("/room/scratch");
  });

  it("filters to the shared or the private rooms", async () => {
    const user = await renderSidebar(["alpha", scratch]);
    const filter = screen.getByRole("radiogroup", { name: "Show rooms" });

    await user.click(within(filter).getByRole("radio", { name: "Private" }));
    expect(screen.queryByRole("link", { name: /alpha/ })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /scratch/ })).toBeInTheDocument();

    await user.click(within(filter).getByRole("radio", { name: "Shared" }));
    expect(screen.getByRole("link", { name: /alpha/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /scratch/ })).not.toBeInTheDocument();
  });

  it("makes a private room when one is typed in the Private view", async () => {
    vi.mocked(createRoom).mockResolvedValue({} as never);
    const user = await renderSidebar(["alpha", scratch]);

    await user.click(screen.getByRole("radio", { name: "Private" }));
    await user.click(screen.getByRole("button", { name: "New room" }));
    await user.keyboard("notes{Enter}");

    expect(createRoom).toHaveBeenCalledWith(expect.objectContaining({ name: "notes", private: true }));
  });
});
