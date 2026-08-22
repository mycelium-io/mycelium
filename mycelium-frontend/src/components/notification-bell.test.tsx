// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { act } from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { FakeEventSource } from "@/test/fake-event-source";
import { resetStreamHub } from "@/lib/stream-hub";

vi.mock("@/lib/api", () => ({
}));

import { CurrentUserProvider } from "@/components/current-user";
import { NotificationsProvider } from "@/components/notifications-provider";
import { NotificationBell } from "@/components/notification-bell";

const CREATED = "2026-08-15T10:00:00.000000+00:00";

function renderBell() {
  return render(
    <CurrentUserProvider>
      <NotificationsProvider>
        <NotificationBell />
      </NotificationsProvider>
    </CurrentUserProvider>,
  );
}

function mention() {
  return {
    id: "msg-1",
    room_name: "sprint",
    sender_handle: "alice",
    message_type: "l9_exchange",
    created_at: CREATED,
    content: JSON.stringify({ content: "hey @bob take a look" }),
  };
}

describe("<NotificationBell />", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.localStorage.setItem("mycelium.principal", "bob");
    resetStreamHub();
    FakeEventSource.reset();
    vi.stubGlobal("EventSource", FakeEventSource);
  });

  it("badges an unread mention and lists it in the popover", async () => {
    const user = userEvent.setup();
    renderBell();
    await act(async () => {});
    const es = FakeEventSource.latest();

    await act(async () => {
      es.open();
      es.emitNotification(mention());
    });

    expect(await screen.findByLabelText("1 unread notifications")).toBeInTheDocument();

    await user.click(screen.getByLabelText("1 unread notifications"));
    expect(await screen.findByText("sprint")).toBeInTheDocument();
    expect(screen.getByText("hey @bob take a look")).toBeInTheDocument();
  });

  it("ignores a message that doesn't mention or address the acting principal", async () => {
    renderBell();
    await act(async () => {});
    const es = FakeEventSource.latest();

    await act(async () => {
      es.open();
      es.emitNotification({
        id: "msg-2",
        room_name: "sprint",
        sender_handle: "alice",
        message_type: "l9_exchange",
        created_at: CREATED,
        content: JSON.stringify({ content: "hey @carol take a look" }),
      });
    });

    expect(screen.getByLabelText("Notifications")).toBeInTheDocument();
    expect(screen.queryByText(/unread/)).not.toBeInTheDocument();
  });

  it("marking all read clears the unread badge", async () => {
    const user = userEvent.setup();
    renderBell();
    await act(async () => {});
    const es = FakeEventSource.latest();

    await act(async () => {
      es.open();
      es.emitNotification(mention());
    });
    await screen.findByLabelText("1 unread notifications");

    await user.click(screen.getByLabelText("1 unread notifications"));
    const panel = await screen.findByText("Notifications");
    await user.click(within(panel.closest("[data-slot=popover-content]")!).getByLabelText("Mark all read"));

    expect(screen.getByLabelText("Notifications")).toBeInTheDocument();
  });

  it("dismissing a notification removes it from the list", async () => {
    const user = userEvent.setup();
    renderBell();
    await act(async () => {});
    const es = FakeEventSource.latest();

    await act(async () => {
      es.open();
      es.emitNotification(mention());
    });
    await user.click(await screen.findByLabelText("1 unread notifications"));
    expect(await screen.findByText("sprint")).toBeInTheDocument();

    await user.click(screen.getByLabelText("Dismiss"));
    expect(screen.queryByText("hey @bob take a look")).not.toBeInTheDocument();
  });
});
