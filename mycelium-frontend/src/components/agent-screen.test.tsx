// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Runner } from "@/lib/api";
import { renderWithSWR } from "@/test/swr";
import { AgentPeek, AgentScreen, STREAMED_LOCALLY } from "./agent-screen";

let runners: Runner[] = [];
vi.mock("@/lib/runners", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/runners")>()),
  useRunners: () => ({ runners, connected: runners, loading: false, refresh: () => {} }),
}));

function runner(id: string, agents: { room: string; handle: string; pane: string }[]): Runner {
  return {
    id,
    label: id === "here" ? "julias-mbp" : "sams-laptop",
    owner: null,
    platform: "darwin-arm64",
    version: "3.0.0",
    herdr: true,
    roots: [],
    frameworks: [],
    agents: agents.map((a) => ({
      ...a,
      framework: "claude",
      status: "running",
      cwd: null,
      started_at: "",
      detail: null,
    })),
    connected: true,
    last_seen: "",
    started_at: "",
  };
}

const calls: [string, unknown][] = [];

/**
 * The desktop app's own hub UI: its user agent, and the command bridge it
 * alone has. Its registry of agents holds @builder of checkout; `machine` is
 * what it answers for which machine it is, null when it has no runner id.
 */
function inTheApp(machine: string | null = "here", refuse?: string) {
  vi.spyOn(navigator, "userAgent", "get").mockReturnValue("Mozilla/5.0 (Macintosh) MyceliumDesktop/3.0.0");
  (globalThis as Record<string, unknown>).__TAURI_INTERNALS__ = {
    invoke: async (command: string, args?: Record<string, unknown>) => {
      calls.push([command, args]);
      if (refuse) throw refuse;
      if (command === "this_machine") return machine;
      if (command === "agent_screen") {
        if (args?.room === "checkout" && args?.handle === "builder")
          return { pane: "w3:p1", text: "\x1b[32m● Reading src/payments.ts\x1b[0m\r\n> " };
        throw "That agent isn't running in a terminal on this machine.";
      }
      return null;
    },
  };
}

beforeEach(() => {
  calls.length = 0;
  runners = [];
});

afterEach(() => {
  vi.restoreAllMocks();
  delete (globalThis as Record<string, unknown>).__TAURI_INTERNALS__;
});

describe("an agent's terminal", () => {
  it("shows live from this machine, and says nothing goes to the hub", async () => {
    inTheApp();
    runners = [runner("here", [{ room: "checkout", handle: "builder", pane: "w3:p1" }])];
    renderWithSWR(<AgentScreen room="checkout" handle="builder" />);

    expect(await screen.findByText("● Reading src/payments.ts")).toBeInTheDocument();
    expect(screen.getByText(STREAMED_LOCALLY)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open its terminal/ })).toHaveAttribute(
      "href",
      "mycelium://terminal?pane=w3%3Ap1",
    );
    // Read from the app by naming the agent, never a pane, and from nowhere else.
    expect(calls).toContainEqual(["agent_screen", { room: "checkout", handle: "builder" }]);
  });

  it("shows the screen whatever the hub's list says, when the app has the agent", async () => {
    // An app that hasn't got a runner id (its runner is someone else's, or
    // not up yet) still knows its own agents.
    inTheApp(null);
    renderWithSWR(<AgentScreen room="checkout" handle="builder" />);
    expect(await screen.findByText("● Reading src/payments.ts")).toBeInTheDocument();
  });

  it("names your other machine when the app says the agent isn't here", async () => {
    inTheApp();
    runners = [runner("elsewhere", [{ room: "checkout", handle: "api", pane: "w1:p1" }])];
    renderWithSWR(<AgentScreen room="checkout" handle="api" />);

    expect(await screen.findByText(/@api runs on sams-laptop/)).toBeInTheDocument();
    expect(screen.queryByText(STREAMED_LOCALLY)).not.toBeInTheDocument();
  });

  it("in the app, on a page the app doesn't count as its own, says why", async () => {
    inTheApp("here", "Not available to this page.");
    renderWithSWR(<AgentScreen room="checkout" handle="builder" />);
    expect(await screen.findByText(/connected to one elsewhere/)).toBeInTheDocument();
  });

  it("says someone else's agent's terminal is theirs", async () => {
    inTheApp();
    renderWithSWR(<AgentScreen room="checkout" handle="web" runner="sams-runner" />);
    expect(await screen.findByText(/someone else's machine/)).toBeInTheDocument();
  });

  it("outside the desktop app, points there and reads nothing", () => {
    runners = [runner("here", [{ room: "checkout", handle: "builder", pane: "w3:p1" }])];
    renderWithSWR(<AgentScreen room="checkout" handle="builder" />);
    expect(screen.getByText(/shows in the desktop app, for agents on that computer/)).toBeInTheDocument();
    expect(screen.queryByText(STREAMED_LOCALLY)).not.toBeInTheDocument();
  });

  it("in the app on a hub elsewhere, says why and never to open the app", async () => {
    vi.spyOn(navigator, "userAgent", "get").mockReturnValue("Mozilla/5.0 (Macintosh) MyceliumDesktop/3.0.0");
    // Client mode: the page is another hub's, so it has no way to ask the app.
    runners = [runner("here", [{ room: "checkout", handle: "builder", pane: "w3:p1" }])];
    renderWithSWR(<AgentScreen room="checkout" handle="builder" />);
    expect(await screen.findByText(/connected to one elsewhere/)).toBeInTheDocument();
    expect(screen.queryByText(/desktop app/)).not.toBeInTheDocument();
  });
});

describe("a peek at an agent's terminal", () => {
  it("shows its last lines when it runs here", async () => {
    inTheApp();
    renderWithSWR(<AgentPeek room="checkout" handle="builder" />);
    expect(await screen.findByText("● Reading src/payments.ts")).toBeInTheDocument();
    expect(screen.getByText("Streamed from this machine")).toBeInTheDocument();
  });

  it("shows nothing where the drawer would only have a note", async () => {
    inTheApp();
    const { container } = renderWithSWR(<AgentPeek room="checkout" handle="api" />);
    await vi.waitFor(() => expect(calls).toContainEqual(["agent_screen", { room: "checkout", handle: "api" }]));
    expect(container).toBeEmptyDOMElement();
  });

  it("shows nothing outside the app, and asks it nothing", () => {
    const { container } = renderWithSWR(<AgentPeek room="checkout" handle="builder" />);
    expect(container).toBeEmptyDOMElement();
    expect(calls).toEqual([]);
  });
});
