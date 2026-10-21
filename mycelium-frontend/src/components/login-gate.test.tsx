// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { fireEvent, render, screen } from "@testing-library/react";
import { SWRConfig } from "swr";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/components/auth-session", () => ({
  useAuthSession: () => ({
    loading: false,
    authRequired: true,
    oidcConfigured: false,
    signInProblem: "This hub accepts sign-in from 2 identity providers.",
    signedIn: false,
    login: () => {},
  }),
}));

import { LoginGate } from "./login-gate";

const gate = () =>
  render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <LoginGate>
        <p>the app</p>
      </LoginGate>
    </SWRConfig>,
  );

describe("<LoginGate /> on a hub you can't sign in to", () => {
  afterEach(() => {
    delete (globalThis as Record<string, unknown>).__TAURI_INTERNALS__;
  });

  it("says why, in place of the app", () => {
    gate();
    expect(screen.getByText("This hub accepts sign-in from 2 identity providers.")).toBeInTheDocument();
    expect(screen.queryByText("the app")).toBeNull();
    // In a browser there is no app to change hubs with.
    expect(screen.queryByRole("button", { name: "Change hub" })).toBeNull();
  });

  it("offers the desktop app's own Hub and Connection, since Settings is behind the same screen", async () => {
    (globalThis as Record<string, unknown>).__TAURI_INTERNALS__ = {
      invoke: async (command: string) =>
        command === "get_state" ? { settings: { mode: "client", hubUrl: "https://hub.example.com", roots: [] } } : false,
    };
    gate();
    fireEvent.click(screen.getByRole("button", { name: "Change hub" }));
    expect(await screen.findByRole("radio", { name: /On this/ })).toBeInTheDocument();
  });
});
