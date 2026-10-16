// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { SWRConfig } from "swr";
import type { HubEditing, HubSettings } from "@/lib/api";
import { fetchHubSettings, restartHub, updateHubSettings } from "@/lib/api";
import { HubPage } from "./hub-page";

vi.mock("@/lib/api", () => ({
  fetchHubSettings: vi.fn(),
  fetchVoiceStatus: vi.fn().mockResolvedValue(null),
  fetchVerifierSettings: vi.fn().mockResolvedValue(null),
  startVerifierLearn: vi.fn(),
  updateHubSettings: vi.fn(),
  restartHub: vi.fn(),
}));
vi.mock("@/lib/use-status", () => ({ useHubHealth: () => ({ data: undefined }) }));
vi.mock("@/lib/room-data", () => ({ useNetworkStatus: () => ({ network: null }) }));
vi.mock("@/components/title-bar", () => ({ useHubLabel: () => "This Mac" }));
vi.mock("@/lib/desktop", async (actual) => ({
  ...(await actual<typeof import("@/lib/desktop")>()),
  useIsDesktop: () => true,
  desktopMachine: () => "Mac",
}));

const DESKTOP: HubEditing = {
  may_edit: true,
  reason: null,
  can_restart: true,
  app_owned: ["voice.enabled", "voice.model", "telemetry.send_product_analytics"],
  pending: [],
  values: {
    "llm.model": "anthropic/claude-sonnet-4-6",
    "llm.base_url": "",
    "llm.api_key": true,
    "verifier.enabled": false,
    "voice.enabled": true,
    "voice.model": "fast",
    "telemetry.send_product_analytics": false,
    "worker.tools": true,
    "worker.pi_timeout_s": 600,
    "worker.max_turns_per_room": 60,
    "board.dependency_gate": false,
  },
};

function hub(editing: Partial<HubEditing> = {}): HubSettings {
  return {
    model: { model: "anthropic/claude-sonnet-4-6", provider: "anthropic", has_key: true, custom_endpoint: false },
    experiences: [],
    personas_only: false,
    share_usage: false,
    workers: { tools: true, turn_timeout_s: 600, max_turns_per_room: 60 },
    dependency_gate: false,
    patterns_inline: true,
    sign_in: false,
    voice: { enabled: true, model: "fast" },
    verifier: false,
    editing: { ...DESKTOP, ...editing },
  };
}

function renderPage() {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <HubPage />
    </SWRConfig>,
  );
}

/** A setting's row by its anchor; throws until it is drawn, so `waitFor` waits. */
function row(id: string): HTMLElement {
  const el = document.getElementById(id);
  if (!el) throw new Error(`no row ${id} yet`);
  return el;
}

beforeEach(() => {
  vi.mocked(updateHubSettings).mockReset().mockResolvedValue({ saved: [], pending: [], restart_needed: true });
  vi.mocked(restartHub).mockReset().mockResolvedValue();
});

describe("<HubPage /> for someone who may change the hub", () => {
  beforeEach(() => vi.mocked(fetchHubSettings).mockResolvedValue(hub()));

  it("saves a switch as soon as it's flipped", async () => {
    renderPage();
    fireEvent.click(await within(await waitFor(() => row("hub.worker-tools"))).findByRole("switch"));
    await waitFor(() => expect(updateHubSettings).toHaveBeenCalledWith({ "worker.tools": false }));
  });

  it("saves a number with Save, as a number", async () => {
    renderPage();
    const turns = await waitFor(() => row("hub.worker-turns"));
    fireEvent.change(within(turns).getByRole("spinbutton"), { target: { value: "30" } });
    fireEvent.click(within(turns).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(updateHubSettings).toHaveBeenCalledWith({ "worker.max_turns_per_room": 30 }));
  });

  it("replaces a key without ever showing it", async () => {
    renderPage();
    const key = await waitFor(() => row("hub.model-key"));
    expect(within(key).getByText("set")).toBeInTheDocument();
    fireEvent.click(within(key).getByRole("button", { name: "Replace…" }));
    const field = within(key).getByLabelText("New API key");
    expect(field).toHaveAttribute("type", "password");
    fireEvent.change(field, { target: { value: "sk-new" } });
    fireEvent.click(within(key).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(updateHubSettings).toHaveBeenCalledWith({ "llm.api_key": "sk-new" }));
  });

  it("says why the hub refused a change", async () => {
    vi.mocked(updateHubSettings).mockRejectedValue(new Error("worker.tools is on or off"));
    renderPage();
    fireEvent.click(await within(await waitFor(() => row("hub.worker-tools"))).findByRole("switch"));
    expect(await screen.findByText("worker.tools is on or off")).toBeInTheDocument();
  });

  it("sends a setting the desktop app sets to the app's settings", async () => {
    renderPage();
    const voice = await waitFor(() => row("hub.voice"));
    expect(within(voice).queryByRole("switch")).toBeNull();
    expect(within(voice).getByRole("link", { name: "Change in Mycelium Settings" })).toHaveAttribute(
      "href",
      "mycelium://settings",
    );
  });

  it("offers a restart once something is saved, and marks what waits for it", async () => {
    vi.mocked(fetchHubSettings).mockResolvedValue(hub({ pending: ["worker.tools"] }));
    renderPage();
    expect(await screen.findByText("1 change is saved and will apply when the hub restarts.")).toBeInTheDocument();
    expect(within(row("hub.worker-tools")).getByText("saved, applies after a restart")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Restart the hub" }));
    await waitFor(() => expect(restartHub).toHaveBeenCalled());
  });
});

describe("<HubPage /> for someone who may not", () => {
  it("shows the values read-only and says why", async () => {
    vi.mocked(fetchHubSettings).mockResolvedValue(
      hub({ may_edit: false, reason: "Only a person can change the hub's settings.", values: {} }),
    );
    renderPage();
    expect(await screen.findByText(/Only a person can change the hub's settings\./)).toBeInTheDocument();
    expect(screen.queryAllByRole("switch")).toHaveLength(0);
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    expect(within(row("hub.worker-turns")).getByText("60")).toBeInTheDocument();
  });
});
