// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { SWRConfig } from "swr";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { CANCELLED } from "@/lib/desktop-app";
import { AppConnection } from "./app-connection";
import { AppModelPage } from "./app-model-page";
import { AppVersionPage } from "./app-version-page";

/** The app's command bridge, as the desktop app gives its own UI. */
const calls: [string, Record<string, unknown> | undefined][] = [];
let answers: Record<string, unknown | ((args?: Record<string, unknown>) => unknown)> = {};

function inTheApp() {
  (globalThis as Record<string, unknown>).__TAURI_INTERNALS__ = {
    invoke: async (command: string, args?: Record<string, unknown>) => {
      calls.push([command, args]);
      const answer = answers[command];
      if (answer instanceof Error) throw answer.message;
      return typeof answer === "function" ? (answer as (a?: Record<string, unknown>) => unknown)(args) : answer;
    },
  };
}

const wrap = (ui: ReactNode) => render(<SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>{ui}</SWRConfig>);
const sent = (command: string) => calls.filter(([c]) => c === command).map(([, a]) => a);

const SAVED = { mode: "hub", hubUrl: null, roots: ["/Users/you/code"], shareUsage: false, voice: false, voiceModel: "fast" };

describe("the app's own settings, in the one Settings", () => {
  beforeEach(() => {
    calls.length = 0;
    answers = {
      get_state: { settings: SAVED, home: "/Users/you", mycelium: {}, herdr: {} },
      get_autostart: false,
      start: { linked: [], skipped: [], onPath: true, line: "" },
    };
    inTheApp();
  });
  afterEach(() => {
    delete (globalThis as Record<string, unknown>).__TAURI_INTERNALS__;
  });

  it("switches this machine to a team's hub through the app, with the rest of its settings kept", async () => {
    wrap(<AppConnection />);
    fireEvent.click(await screen.findByRole("radio", { name: "On my team's hub" }));
    fireEvent.change(screen.getByRole("textbox", { name: "The hub's address" }), { target: { value: " https://hub.example.com " } });
    fireEvent.click(screen.getByRole("button", { name: "Switch" }));
    await waitFor(() => expect(sent("start")).toHaveLength(1));
    expect(sent("start")[0]).toEqual({
      settings: { ...SAVED, mode: "client", hubUrl: "https://hub.example.com", shareUsage: false, voice: false },
    });
  });

  it("says nothing when the person said no on the machine", async () => {
    answers.start = new Error(CANCELLED);
    wrap(<AppConnection />);
    fireEvent.click(await screen.findByRole("radio", { name: "On my team's hub" }));
    fireEvent.change(screen.getByRole("textbox", { name: "The hub's address" }), { target: { value: "https://hub.example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Switch" }));
    await waitFor(() => expect(sent("start")).toHaveLength(1));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("never sends back a key it was never given: an untouched key stays saved", async () => {
    answers.get_model = { model: "anthropic/claude-sonnet-4-6", base_url: null, has_key: true, key_hint: "a1b2" };
    answers.run_doctor = { checks: [] };
    answers.save_model = {};
    wrap(<AppModelPage />);
    expect(await screen.findByText("Key saved")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "Model" }), { target: { value: "anthropic/claude-opus-4-6" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(sent("start")).toHaveLength(1));
    expect(sent("save_model")[0]).toEqual({ model: { model: "anthropic/claude-opus-4-6", base_url: "" } });
  });

  it("lists releases to switch to, and warns before going back to an older one", async () => {
    answers.app_versions = (args?: Record<string, unknown>) => ({
      current: "3.0.55",
      releaseCandidates: false,
      releases: [
        { tag: "v3.0.55", version: "3.0.55", prerelease: false, published: "" },
        { tag: "v3.0.54", version: "3.0.54", prerelease: false, published: "" },
        ...(args?.withRc ? [{ tag: "v3.0.56rc1", version: "3.0.56-rc1", prerelease: true, published: "" }] : []),
      ],
    });
    answers.switch_version = null;
    wrap(<AppVersionPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Switch back" }));
    expect(sent("switch_version")).toHaveLength(0);
    expect(screen.getByText(/older than the version you have/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Switch to v3.0.54 anyway" }));
    await waitFor(() => expect(sent("switch_version")).toEqual([{ tag: "v3.0.54" }]));
    expect(await screen.findByText(/Downloading 3.0.54/)).toBeInTheDocument();
  });
});
