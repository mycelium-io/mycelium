// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithSWR } from "@/test/swr";

vi.mock("@/lib/api", () => ({
  fetchNetworkStatus: vi.fn(),
  logFetchError: () => () => undefined,
}));

import { RoomSlimView } from "@/components/room-slim";
import { fetchNetworkStatus, type NetworkStatus } from "@/lib/api";

const mocked = vi.mocked(fetchNetworkStatus);

function coordination() {
  return {
    endpoint: "http://slim:46357",
    slim_enabled: true,
    channels_live: 1,
    provisions_ok: 1,
    provisions_failed: 0,
    invite_failures: 0,
    rooms: [
      {
        room: "sprint",
        provisioned: true,
        persister_alive: true,
        members: ["alice"],
        pending_invites: 0,
        episode_active: false,
        reserves: 0,
        reserve_failures: 0,
        reserve_skipped: 0,
        receive_errors: 0,
        transient_errors: 0,
      },
    ],
  };
}

function net(overrides: Partial<NetworkStatus> = {}): NetworkStatus {
  return {
    coordination: coordination(),
    identity: { status: "ok", mode: "psk", message: "psk" },
    auth: { enabled: false, issuers: [], localhost_bypass: true, audience: null },
    ...overrides,
  };
}

async function draw(layout: "full" | "rail", status: NetworkStatus | null) {
  mocked.mockResolvedValue(status);
  renderWithSWR(<RoomSlimView roomName="sprint" layout={layout} />);
  // Let the shared /health read settle before asserting on what it rendered.
  await screen.findByText(layout === "rail" ? "identity" : "Channel identity");
}

describe("RoomSlimView identity + auth", () => {
  beforeEach(() => {
    mocked.mockReset();
  });

  it("shows the identity tier and an off auth gate in the rail", async () => {
    await draw("rail", net());
    expect(screen.getByText("psk")).toBeTruthy();
    expect(screen.getByText("off")).toBeTruthy();
  });

  it("keeps the rail to the two posture stats under the default posture", async () => {
    await draw("rail", net());
    expect(screen.queryByText("trusts")).toBeNull();
  });

  it("spells the degrade out on the rail when signerjwt is not actually in force", async () => {
    await draw("rail", {
      ...net(),
      identity: {
        status: "degraded",
        mode: "signerjwt",
        message: "signerjwt selected but no resolvable signing key/roster — degrading to PSK",
      },
    });
    expect(screen.getByText("signerjwt")).toBeTruthy();
    expect(screen.getByText(/degrading to PSK/)).toBeTruthy();
  });

  it("names the trusted issuer on the rail when the gate is on", async () => {
    await draw("rail", {
      ...net(),
      auth: {
        enabled: true,
        issuers: ["https://idp.example.com"],
        localhost_bypass: false,
        audience: "mycelium",
      },
    });
    expect(screen.getByText("on")).toBeTruthy();
    expect(screen.getByText("https://idp.example.com")).toBeTruthy();
  });

  it("names the trusted issuer when the gate is on", async () => {
    await draw("full", {
      ...net(),
      auth: {
        enabled: true,
        issuers: ["https://idp.example.com"],
        localhost_bypass: false,
        audience: "mycelium",
      },
    });
    expect(screen.getByText("enabled")).toBeTruthy();
    expect(screen.getByText("https://idp.example.com")).toBeTruthy();
    expect(screen.getByText("mycelium")).toBeTruthy();
  });

  it("surfaces a configured audience warning from the backend", async () => {
    await draw("full", {
      ...net(),
      auth: {
        enabled: true,
        issuers: ["https://idp.example.com"],
        localhost_bypass: false,
        audience: null,
        warnings: ["no audience configured — any token from a trusted issuer is accepted"],
      },
    });
    expect(screen.getByText(/no audience configured/)).toBeTruthy();
    // With no audience set, the gate accepts any — say so rather than blanking.
    expect(screen.getByText("any")).toBeTruthy();
  });

  it("reports a signerjwt hub with no resolvable key/roster as degraded, not in force", async () => {
    await draw("full", {
      ...net(),
      identity: {
        status: "degraded",
        mode: "signerjwt",
        message: "signerjwt selected but no resolvable signing key/roster — degrading to PSK",
      },
    });
    expect(screen.getByText("degraded")).toBeTruthy();
    expect(screen.getByText(/degrading to PSK/)).toBeTruthy();
  });

  it("falls back to the unreachable notice when /health does not answer", async () => {
    mocked.mockResolvedValue(null);
    renderWithSWR(<RoomSlimView roomName="sprint" layout="full" />);
    expect(await screen.findByText("Backend unreachable.")).toBeTruthy();
  });
});
