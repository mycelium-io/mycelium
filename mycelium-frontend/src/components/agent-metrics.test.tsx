// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderWithSWR } from "@/test/swr";
import type { AgentUsage, AgentsUsage } from "@/lib/api";

const fetchAgentsUsage = vi.fn();
const controlAgent = vi.fn();
const keepAgent = vi.fn();
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  fetchAgentsUsage: (...args: unknown[]) => fetchAgentsUsage(...args),
  controlAgent: (...args: unknown[]) => controlAgent(...args),
  keepAgent: (...args: unknown[]) => keepAgent(...args),
}));

import { CurrentUserProvider } from "@/components/current-user";
import { AgentMetricsView, ram, totalMb } from "./agent-metrics";

const ago = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();

function row(over: Partial<AgentUsage> & Pick<AgentUsage, "handle">): AgentUsage {
  return {
    room: "eng",
    owner: "julia",
    state: "idle",
    kind: "claude",
    runner: "mac",
    machine: "julia-mbp",
    pane: `w1:${over.handle}`,
    keep: false,
    ram_mb: 500,
    cpu: 0,
    up_s: 60,
    idle_since: null,
    processes: [],
    subagents_open: null,
    restartable: false,
    ...over,
  };
}

const USAGE: AgentsUsage = {
  machines: [{ runner: "mac", machine: "julia-mbp", ram_total_mb: 16384 }],
  agents: [
    row({
      handle: "builder",
      state: "working",
      keep: true,
      ram_mb: 1240,
      cpu: 34,
      processes: [{ name: "claude", command: "claude --resume …", ram_mb: 812 }],
    }),
    row({ handle: "research", idle_since: ago(300), ram_mb: 980 }),
    row({ handle: "fresh", idle_since: ago(10), ram_mb: 300 }),
    row({ handle: "pinned", idle_since: ago(600), keep: true }),
    row({ handle: "theirs", owner: "sam", idle_since: ago(600), ram_mb: 700 }),
    row({ handle: "napping", state: "stopped", ram_mb: null, restartable: true }),
  ],
};

function renderPane() {
  return renderWithSWR(
    <CurrentUserProvider>
      <AgentMetricsView roomName="eng" />
    </CurrentUserProvider>,
  );
}

describe("the Agents pane", () => {
  beforeEach(() => {
    window.localStorage.setItem("mycelium.principal", "julia");
    fetchAgentsUsage.mockReset().mockResolvedValue(USAGE);
    controlAgent.mockReset().mockResolvedValue({});
    keepAgent.mockReset().mockResolvedValue({});
  });

  it("reads memory the way a person does", () => {
    expect(ram(640)).toBe("640 MB");
    expect(ram(1240)).toBe("1.2 GB");
    // 1240 + 980 + 300 + 500 + 700; a stopped agent holds nothing.
    expect(totalMb(USAGE.agents)).toBe(3720);
  });

  it("shows each machine's share and each agent, heaviest first", async () => {
    renderPane();
    expect(await screen.findByText("research")).toBeTruthy();
    expect(screen.getByText("of 16.0 GB")).toBeTruthy();
    // builder's processes are a click away.
    fireEvent.click(screen.getByText("builder"));
    expect(screen.getByText("claude --resume …")).toBeTruthy();
  });

  it("offers only your own agents to pick, and picks the idle ones that aren't kept", async () => {
    renderPane();
    await screen.findByText("research");
    // Sam's agent is shown, never picked: the hub would refuse.
    expect(screen.queryByLabelText("Pick theirs")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Pick idle for an hour/ }));
    expect((screen.getByLabelText("Pick research") as HTMLInputElement).checked).toBe(true);
    expect((screen.getByLabelText("Pick fresh") as HTMLInputElement).checked).toBe(false);
    expect((screen.getByLabelText("Pick pinned") as HTMLInputElement).checked).toBe(false);
    expect(screen.getByText("Stopping frees 980 MB")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /Stop 1/ }));
    await waitFor(() => expect(controlAgent).toHaveBeenCalledWith("eng", "research", "stop", "julia"));
    expect(controlAgent).toHaveBeenCalledTimes(1);
  });

  it("starts a stopped agent and pins one to keep running", async () => {
    renderPane();
    const stopped = (await screen.findByText("napping")).closest("tr") as HTMLElement;
    fireEvent.click(within(stopped).getByRole("button", { name: /Start/ }));
    await waitFor(() => expect(controlAgent).toHaveBeenCalledWith("eng", "napping", "start", "julia"));

    fireEvent.click(screen.getByRole("button", { name: "Keep research running" }));
    await waitFor(() => expect(keepAgent).toHaveBeenCalledWith("eng", "research", true, "julia"));
  });

  it("says so when no machine reports anything", async () => {
    fetchAgentsUsage.mockResolvedValue({ machines: [], agents: [] });
    renderPane();
    expect(await screen.findByText(/No machine reports what this room/)).toBeTruthy();
  });
});
