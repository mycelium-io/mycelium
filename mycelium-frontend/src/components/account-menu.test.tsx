// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const network = vi.fn();
vi.mock("@/lib/room-data", () => ({
  useNetworkStatus: () => network(),
}));

const auth = vi.fn();
vi.mock("@/components/auth-session", () => ({ useAuthSession: () => auth() }));
vi.mock("@/components/current-user", () => ({ useCurrentUser: () => ({ principal: "foobar", setPrincipal: () => {} }) }));
vi.mock("@/components/keymap-provider", () => ({ useCommands: () => {} }));
vi.mock("@/lib/people", () => ({ nameOf: () => undefined, useNames: () => ({}), useRefreshUsers: () => () => {} }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: () => {} }) }));

import { AboutView, AccountMenu, MenuView } from "@/components/account-menu";

const session = (over: object) => ({
  authRequired: false,
  oidcConfigured: false,
  signedIn: false,
  handle: null,
  login: vi.fn(),
  logout: vi.fn(),
  ...over,
});

describe("<AccountMenu />", () => {
  it("puts Sign in in the corner when the hub offers a sign-in you haven't made", () => {
    const s = session({ oidcConfigured: true });
    auth.mockReturnValue(s);
    render(<AccountMenu />);
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(s.login).toHaveBeenCalledOnce();
  });

  it("never shows this browser's name as you on a hub that asks for sign-in", () => {
    auth.mockReturnValue(session({ authRequired: true, oidcConfigured: true }));
    render(<AccountMenu />);
    expect(screen.queryByRole("button", { name: /foobar/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Choose your name" })).toBeInTheDocument();
  });

  it("shows no Sign in button once you're signed in", () => {
    auth.mockReturnValue(session({ authRequired: true, oidcConfigured: true, signedIn: true, handle: "julia" }));
    render(<AccountMenu />);
    expect(screen.queryByRole("button", { name: "Sign in" })).toBeNull();
    expect(screen.getByRole("button", { name: /@julia/ })).toBeInTheDocument();
  });
});

describe("<MenuView />", () => {
  it("offers Settings, which goes to the settings pages", () => {
    const onSettings = vi.fn();
    render(
      <MenuView
        me="julia"
        signedIn={false}
        canSignIn={false}
        onGo={() => {}}
        onSettings={onSettings}
        onSignIn={() => {}}
        onSignOut={() => {}}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Settings/ }));
    expect(onSettings).toHaveBeenCalledOnce();
  });
});

describe("<AboutView />", () => {
  it("shows the hub's release and links to its notes", () => {
    network.mockReturnValue({ network: { version: "3.0.14" }, loading: false });
    render(<AboutView />);

    expect(screen.getByText("v3.0.14")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Release notes/ })).toHaveAttribute(
      "href",
      "https://github.com/mycelium-io/mycelium/releases/tag/v3.0.14",
    );
    expect(screen.getByRole("link", { name: /Changelog/ })).toHaveAttribute("target", "_blank");
    // In a browser there is no app version to show.
    expect(screen.queryByText("Desktop app")).toBeNull();
  });

  it("calls an unreleased hub a development build, not a placeholder version", () => {
    network.mockReturnValue({ network: { version: "0.1.0" }, loading: false });
    render(<AboutView />);

    expect(screen.getByText("development build")).toBeInTheDocument();
    expect(screen.queryByText("v0.1.0")).toBeNull();
    expect(screen.getByRole("link", { name: /Releases/ })).toHaveAttribute(
      "href",
      "https://github.com/mycelium-io/mycelium/releases",
    );
  });

  it("says when the hub can't be reached", () => {
    network.mockReturnValue({ network: null, loading: false });
    render(<AboutView />);
    expect(screen.getByText("unreachable")).toBeInTheDocument();
  });

  it("shows the desktop app's own version inside the app", () => {
    network.mockReturnValue({ network: { version: "3.0.14" }, loading: false });
    const ua = vi.spyOn(navigator, "userAgent", "get").mockReturnValue("WebKit MyceliumDesktop/3.0.12");
    render(<AboutView />);

    expect(screen.getByText("Desktop app")).toBeInTheDocument();
    expect(screen.getByText("v3.0.12")).toBeInTheDocument();
    ua.mockRestore();
  });
});
