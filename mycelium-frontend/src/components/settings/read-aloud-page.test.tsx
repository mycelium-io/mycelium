// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SWRConfig } from "swr";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { FakeEventSource } from "@/test/fake-event-source";
import { resetStreamHub } from "@/lib/stream-hub";

const hub = { speech: true };
vi.mock("@/lib/api", () => ({
  fetchMemories: vi.fn(async () => []),
  fetchRooms: vi.fn(async () => [{ name: "sprint" }, { name: "lobby" }]),
  fetchVoiceStatus: vi.fn(async () => ({ state: "ready", speech: hub.speech })),
  fetchSpeechVoices: vi.fn(async () => ({ voices: ["af_heart", "bm_george"], default: "af_heart" })),
  fetchSpeech: vi.fn(),
  logFetchError: () => () => undefined,
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }), usePathname: () => "/settings/read-aloud" }));

import { CurrentUserProvider } from "@/components/current-user";
import { NotificationsProvider } from "@/components/notifications-provider";
import { ReadAloudPage } from "./read-aloud-page";

function renderPage() {
  return render(
    <SWRConfig value={{ provider: () => new Map() }}>
      <CurrentUserProvider>
        <NotificationsProvider>
          <ReadAloudPage />
        </NotificationsProvider>
      </CurrentUserProvider>
    </SWRConfig>,
  );
}

const saved = () => JSON.parse(window.localStorage.getItem("mycelium.notification-settings") ?? "{}");

describe("<ReadAloudPage />", () => {
  beforeEach(() => {
    window.localStorage.clear();
    hub.speech = true;
    resetStreamHub();
    FakeEventSource.reset();
    vi.stubGlobal("EventSource", FakeEventSource);
  });

  it("says what's missing when the hub has no speech server", async () => {
    hub.speech = false;
    renderPage();
    expect(await screen.findByText(/This hub has no speech server/)).toBeInTheDocument();
    expect(screen.queryByRole("switch", { name: "Read aloud" })).not.toBeInTheDocument();
  });

  it("offers every choice, starting where nothing has been changed", async () => {
    renderPage();
    expect(await screen.findByRole("radio", { name: "Mentions of me" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "The thread I have open" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "The start" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "Normal" })).toHaveAttribute("aria-checked", "true");
  });

  it("saves what each person picks", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole("radio", { name: "Everything in rooms I pick" }));
    await user.click(await screen.findByRole("button", { name: "sprint" }));
    await user.click(screen.getByRole("radio", { name: "Nothing" }));
    await user.click(screen.getByRole("radio", { name: "All of it" }));
    await user.click(screen.getByRole("radio", { name: "1.25×" }));
    await user.selectOptions(await screen.findByRole("combobox", { name: "Voice" }), "bm_george");
    expect(saved()).toMatchObject({
      readAloudReads: "rooms",
      readAloudRooms: ["sprint"],
      readAloudSkip: "never",
      readAloudLength: "all",
      readAloudSpeed: 1.25,
      readAloudVoice: "bm_george",
    });
  });
});
