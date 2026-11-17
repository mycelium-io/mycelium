// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderWithSWR } from "@/test/swr";
import type { AgentRunning } from "@/lib/api";
import type { LocalUsage } from "@/lib/desktop";

const fetchAgentsRunning = vi.fn();
const controlAgent = vi.fn();
const keepAgent = vi.fn();
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  fetchAgentsRunning: (...args: unknown[]) => fetchAgentsRunning(...args),
  controlAgent: (...args: unknown[]) => controlAgent(...args),
  keepAgent: (...args: unknown[]) => keepAgent(...args),
}));

import { CurrentUserProvider } from "@/components/current-user";
import { AgentMetricsView, localMb, ram } from "./agent-metrics";

const HERE = "julias-mbp";

function row(over: Partial<AgentRunning> & Pick<AgentRunning, "handle">): AgentRunning {
  return {
    room: "eng",
    owner: "julia",
    state: "idle",
    kind: "claude",
    runner: HERE,
    machine: "julia-mbp",
    pane: `w1:${over.handle}`,
    keep: false,
    restartable: false,
    ...over,
  };
}

const RUNNING: AgentRunning[] = [
  row({ handle: "builder", state: "working", keep: true }),
  row({ handle: "research" }),
  row({ handle: "voice", state: "paused" }),
  row({ handle: "asking", state: "blocked" }),
  row({ handle: "pinned", keep: true }),
  row({ handle: "theirs", owner: "sam", runner: "sams-mini", machine: "sams-mini" }),
  row({ handle: "napping", state: "stopped", restartable: true }),
];

const ago = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();

const LOCAL: LocalUsage = {
  runner: HERE,
  ram_total_mb: 16384,
  agents: [
    {
      room: "eng",
      handle: "builder",
      pane: "w1:builder",
      ram_mb: 1240,
      cpu: 34,
      up_s: 60,
      idle_since: null,
      processes: [{ name: "claude", command: "claude --resume …", ram_mb: 812 }],
    },
    { room: "eng", handle: "research", pane: "w1:research", ram_mb: 980, cpu: 0, up_s: 60, idle_since: ago(300), processes: [] },
  ],
};

/** The desktop app's bridge, answering `agent_usage` with this computer's numbers. */
function inTheApp(usage: LocalUsage | null) {
  (globalThis as Record<string, unknown>).__TAURI_INTERNALS__ = {
    invoke: async (command: string) => (command === "agent_usage" ? usage : null),
  };
}

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
    fetchAgentsRunning.mockReset().mockResolvedValue(RUNNING);
    controlAgent.mockReset().mockResolvedValue({});
    keepAgent.mockReset().mockResolvedValue({});
  });
  afterEach(() => {
    delete (globalThis as Record<string, unknown>).__TAURI_INTERNALS__;
  });

  it("reads memory the way a person does", () => {
    expect(ram(640)).toBe("640 MB");
    expect(ram(1240)).toBe("1.2 GB");
    expect(localMb(LOCAL)).toBe(2220);
    expect(localMb(null)).toBe(0);
  });

  it("shows numbers for this computer's agents only, read on this computer", async () => {
    inTheApp(LOCAL);
    renderPane();
    expect(await screen.findByText("Numbers are for this computer only. They never leave it.")).toBeTruthy();
    expect(screen.getByText("of 16.0 GB")).toBeTruthy();
    const builder = screen.getByText("builder").closest("tr") as HTMLElement;
    expect(within(builder).getByText("1.2 GB")).toBeTruthy();
    // Sam's agent elsewhere: its state and machine, no numbers, and it doesn't open.
    const theirs = screen.getByText("theirs").closest("tr") as HTMLElement;
    expect(within(theirs).getByText("sams-mini")).toBeTruthy();
    expect(within(theirs).queryByText(/MB|GB|%/)).toBeNull();
    // builder's processes are a click away.
    fireEvent.click(screen.getByText("builder"));
    expect(screen.getByText("claude --resume …")).toBeTruthy();
  });

  it("has no numbers at all outside the desktop app", async () => {
    renderPane();
    expect(await screen.findByText("research")).toBeTruthy();
    expect(screen.queryByText(/They never leave it/)).toBeNull();
    expect(screen.queryByText(/GB|MB/)).toBeNull();
  });

  it("shows idle and paused agents under Idle, never kept ones, and selects them all at once", async () => {
    inTheApp(LOCAL);
    renderPane();
    await screen.findByText("research");
    fireEvent.click(screen.getByRole("tab", { name: /Idle/ }));
    // Not working, not waiting on a person, not kept, not stopped.
    expect(screen.queryByText("builder")).toBeNull();
    expect(screen.queryByText("asking")).toBeNull();
    expect(screen.queryByText("pinned")).toBeNull();
    // Sam's is shown, never selectable: the hub would refuse.
    expect(screen.getByText("theirs")).toBeTruthy();
    expect(screen.queryByLabelText("Select theirs")).toBeNull();

    fireEvent.click(screen.getByLabelText("Select all"));
    expect(screen.getByText("2 selected")).toBeTruthy();
    expect(screen.getByText("Stopping frees 980 MB")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Stop 2/ }));
    await waitFor(() => expect(controlAgent).toHaveBeenCalledTimes(2));
    expect(controlAgent).toHaveBeenCalledWith("eng", "research", "stop", "julia");
    expect(controlAgent).toHaveBeenCalledWith("eng", "voice", "stop", "julia");
  });

  it("starts a stopped agent and pins one to keep running", async () => {
    renderPane();
    const stopped = (await screen.findByText("napping")).closest("tr") as HTMLElement;
    fireEvent.click(within(stopped).getByRole("button", { name: /Start/ }));
    await waitFor(() => expect(controlAgent).toHaveBeenCalledWith("eng", "napping", "start", "julia"));

    fireEvent.click(screen.getByRole("button", { name: "Keep research running" }));
    await waitFor(() => expect(keepAgent).toHaveBeenCalledWith("eng", "research", true, "julia"));
  });
});
