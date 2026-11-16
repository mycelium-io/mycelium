// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { SWRConfig } from "swr";
import { afterEach, describe, expect, it } from "vitest";
import type { Widget, Widgets } from "@/lib/widgets";
import { WidgetsCard } from "./widgets-card";

const wrap = (ui: ReactNode) => render(<SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>{ui}</SWRConfig>);

/** The app's bridge, answering `widgets` with ``answer``. */
function inTheApp(answer: Widgets | null) {
  (globalThis as Record<string, unknown>).__TAURI_INTERNALS__ = {
    invoke: async (command: string) => (command === "widgets" ? answer : null),
  };
}

const widget = (over: Partial<Widget>): Widget => ({
  label: "x",
  command: "echo x",
  text: null,
  every: "1m",
  timeout: 10,
  icon: "text",
  meter: false,
  run: null,
  ...over,
});

const ran = { exit: 0, timed_out: false, error: null, ran_at: "2026-11-15T10:00:00+00:00" };

describe("the Widgets card", () => {
  afterEach(() => {
    delete (globalThis as Record<string, unknown>).__TAURI_INTERNALS__;
  });

  it("shows each widget's value, a meter for a percentage, and which failed or hung", async () => {
    inTheApp({
      config: "/Users/you/.mycelium/config.toml",
      error: null,
      widgets: [
        widget({ label: "RAM free", icon: "memory", meter: true, run: { ...ran, ok: true, value: "38%" } }),
        widget({ label: "hub", command: null, text: "Mac mini" }),
        widget({ label: "CI", icon: "ci", run: { ...ran, ok: false, value: null, exit: 4, error: "gh: run gh auth login" } }),
        widget({ label: "slow", run: { ...ran, ok: false, value: null, exit: null, timed_out: true } }),
      ],
    });
    const { container } = wrap(<WidgetsCard />);
    expect(await screen.findByText("38%")).toBeTruthy();
    expect(screen.getByText("Mac mini")).toBeTruthy();
    expect(screen.getByText("Failed")).toBeTruthy();
    expect(screen.getByText("Hung")).toBeTruthy();
    // No heading; every tile opens Settings at the widgets.
    expect(screen.queryByText("Widgets")).toBeNull();
    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(4);
    for (const link of links) expect(link.getAttribute("href")).toBe("/settings/widgets");
    // RAM free's bar, filled to its value; no other row has one.
    const bars = container.querySelectorAll("span[style*='width']");
    expect(bars).toHaveLength(1);
    expect((bars[0] as HTMLElement).style.width).toBe("38%");
  });

  it("draws what a run's JSON set over the config: markdown text, color, dot, meter", async () => {
    inTheApp({
      config: "/Users/you/.mycelium/config.toml",
      error: null,
      widgets: [
        widget({
          label: "RAM",
          icon: "memory-stick",
          color: "accent",
          run: {
            ...ran,
            ok: true,
            value: "**38%** free",
            fields: { color: "yellow", state: "warn", meter: 61, tooltip: "Swap is *2.1G*" },
          },
        }),
        widget({ label: "mood", command: null, text: "🚀 *shipping*", icon: "🚀" }),
      ],
    });
    const { container } = wrap(<WidgetsCard />);
    const bold = await screen.findByText("38%");
    expect(bold.tagName).toBe("STRONG");
    // The run's color wins over the config's, on the text.
    expect(bold.closest(".text-yellow")).toBeTruthy();
    expect(screen.getByText("shipping").tagName).toBe("EM");
    // Its own dot, in its state's tone.
    expect(container.querySelector("span[style*='--yellow']")).toBeTruthy();
    // The bar is the run's number, not a percentage read from the text.
    const bar = container.querySelector("span[style*='width']") as HTMLElement;
    expect(bar.style.width).toBe("61%");
    // An emoji is drawn as itself.
    expect(screen.getAllByText("🚀").length).toBeGreaterThan(0);
  });

  it("puts a failed run's dot over the state a config sets", async () => {
    inTheApp({
      config: "/Users/you/.mycelium/config.toml",
      error: null,
      widgets: [widget({ label: "CI", state: "ok", run: { ...ran, ok: false, value: null, exit: 1 } })],
    });
    const { container } = wrap(<WidgetsCard />);
    expect(await screen.findByText("Failed")).toBeTruthy();
    expect(container.querySelectorAll("span[style*='background']")).toHaveLength(1);
    expect(container.querySelector("span[style*='--green']")).toBeNull();
  });

  it("is nothing at all with no widgets", async () => {
    inTheApp({ config: "/Users/you/.mycelium/config.toml", error: null, widgets: [] });
    const { container } = wrap(<WidgetsCard />);
    await new Promise((r) => setTimeout(r, 20));
    expect(container.innerHTML).toBe("");
  });

  it("is nothing at all outside the desktop app", () => {
    const { container } = wrap(<WidgetsCard />);
    expect(container.innerHTML).toBe("");
  });
});
