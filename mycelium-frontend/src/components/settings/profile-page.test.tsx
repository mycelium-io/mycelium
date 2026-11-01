// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { __resetClientSettingsCache } from "@/lib/client-settings";
import { ProfilePage } from "./profile-page";

vi.mock("@/components/current-user", () => ({
  useCurrentUser: () => ({ principal: "julia", setPrincipal: vi.fn() }),
}));
vi.mock("@/components/auth-session", () => ({
  useAuthSession: () => ({ signedIn: false, handle: null }),
}));
vi.mock("@/lib/people", () => ({
  useUsers: () => ({ users: [{ handle: "julia", display_name: "Julia Valenti", owns: [] }] }),
  useRefreshUsers: () => vi.fn(),
}));
vi.mock("@/lib/api", () => ({ createUser: vi.fn(), logFetchError: vi.fn() }));

beforeEach(() => {
  window.localStorage.clear();
  __resetClientSettingsCache();
});

describe("<ProfilePage />", () => {
  it("shows you as your initials, even with agents shown as creatures", () => {
    // Creatures are the default for agents; a person must never become one.
    const { container } = render(<ProfilePage />);
    expect(screen.getByText("JU")).toBeInTheDocument();
    expect(container.querySelector("svg[data-family]")).toBeNull();
  });
});
