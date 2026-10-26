// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { fireEvent, screen, waitFor } from "@testing-library/react";
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
/** What @builder's terminal shows on the app's next read. */
let builderScreen = "\x1b[32m● Reading src/payments.ts\x1b[0m\r\n> ";

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
          return { pane: "w3:p1", text: builderScreen };
        throw "That agent isn't running in a terminal on this machine.";
      }
      return null;
    },
  };
}

beforeEach(() => {
  calls.length = 0;
  runners = [];
  builderScreen = "\x1b[32m● Reading src/payments.ts\x1b[0m\r\n> ";
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

  it("fills a view wider than the terminal, and keeps a dark terminal's colors readable on a light page", async () => {
    // A light page, a view 1200px wide and characters 6px wide at its usual 12px.
    const real = window.getComputedStyle;
    vi.spyOn(window, "getComputedStyle").mockImplementation(
      (el) =>
        ({
          color: "rgb(30, 30, 30)",
          backgroundColor: "rgb(250, 245, 230)",
          fontSize: "12px",
          fontFamily: "monospace",
          paddingLeft: "12px",
          paddingRight: "12px",
          getPropertyValue: (name: string) => real(el).getPropertyValue(name),
        }) as unknown as CSSStyleDeclaration,
    );
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(1200);
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({ width: 120 } as DOMRect);
    inTheApp();
    renderWithSWR(<AgentScreen room="checkout" handle="builder" />);

    const line = await screen.findByText("● Reading src/payments.ts");
    // Its text grows to fill the width, up to 2.25 times its size.
    await waitFor(() => expect(screen.getByLabelText("Its terminal").style.fontSize).toBe("27px"));
    // The terminal's green, picked for a dark background, is darkened to be read on cream.
    await waitFor(() => expect(line.style.color).not.toBe("rgb(78, 154, 6)"));
    expect(line.style.color).toMatch(/^rgb\(/);
  });

  it("opens at the bottom of the scrollback, where the terminal is now", async () => {
    // A view over a terminal with more lines than fit shows the newest, not
    // the oldest lines it was handed.
    vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockReturnValue(1000);
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(200);
    inTheApp();
    renderWithSWR(<AgentScreen room="checkout" handle="builder" />);
    const view = await screen.findByLabelText("Its terminal");
    expect(view.scrollTop).toBe(1000);
  });

  it("holds what was on it while scrolled up, and follows again back at the bottom", async () => {
    vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockReturnValue(1000);
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(200);
    inTheApp();
    renderWithSWR(<AgentScreen room="checkout" handle="builder" />);
    const view = await screen.findByLabelText("Its terminal");
    await screen.findByText("● Reading src/payments.ts");

    // Scrolled up to read; the terminal moves on meanwhile.
    view.scrollTop = 100;
    fireEvent.scroll(view);
    builderScreen = "● Running the tests\r\n> ";
    await waitFor(() => expect(calls.filter(([c]) => c === "agent_screen").length).toBeGreaterThan(1), {
      timeout: 3000,
    });
    expect(screen.getByText("● Reading src/payments.ts")).toBeInTheDocument();
    expect(screen.queryByText("● Running the tests")).not.toBeInTheDocument();

    // Back at the bottom: where the terminal is now.
    view.scrollTop = 800;
    fireEvent.scroll(view);
    expect(await screen.findByText("● Running the tests")).toBeInTheDocument();
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
