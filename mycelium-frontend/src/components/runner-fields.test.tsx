// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const env = { mac: true, desktop: false };

vi.mock("@/lib/client-hooks", () => ({ useIsMac: () => env.mac }));
vi.mock("@/lib/desktop", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/desktop")>()),
  useIsDesktop: () => env.desktop,
}));

import { ConnectMachine } from "./runner-fields";
import { DMG_URL } from "@/lib/desktop";

describe("<ConnectMachine />", () => {
  beforeEach(() => {
    env.mac = true;
    env.desktop = false;
  });

  it("offers the Mac app first in a browser on a Mac", () => {
    render(<ConnectMachine />);
    expect(screen.getByRole("link", { name: /Get Mycelium for Mac/ })).toHaveAttribute("href", DMG_URL);
    expect(screen.getByText(/Or run this in a terminal/)).toBeInTheDocument();
  });

  it("leaves the app out inside the app", () => {
    env.desktop = true;
    render(<ConnectMachine />);
    expect(screen.queryByRole("link", { name: /Get Mycelium for Mac/ })).not.toBeInTheDocument();
    expect(screen.getByText(/^Run this in a terminal/)).toBeInTheDocument();
  });

  it("leaves the app out on a system it doesn't run on", () => {
    env.mac = false;
    render(<ConnectMachine />);
    expect(screen.queryByRole("link", { name: /Get Mycelium for Mac/ })).not.toBeInTheDocument();
  });
});
