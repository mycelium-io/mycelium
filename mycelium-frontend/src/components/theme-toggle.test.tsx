// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const theme = { current: "dark" };
vi.mock("next-themes", () => ({
  useTheme: () => ({
    theme: theme.current,
    resolvedTheme: theme.current,
    setTheme: (t: string) => {
      theme.current = t;
    },
  }),
}));
vi.mock("@/components/keymap-provider", () => ({ useCommands: () => {} }));

import { ThemeToggle } from "@/components/theme-toggle";
import { __resetClientSettingsCache } from "@/lib/client-settings";

async function openMenu() {
  const user = userEvent.setup();
  render(<ThemeToggle />);
  await user.click(screen.getByRole("button", { name: "Theme" }));
  return user;
}

describe("<ThemeToggle /> previews", () => {
  beforeEach(() => {
    window.localStorage.clear();
    __resetClientSettingsCache();
    theme.current = "dark";
  });

  it("shows a hovered theme and puts yours back when the pointer leaves the menu", async () => {
    const user = await openMenu();
    await user.hover(screen.getByRole("button", { name: "Dracula" }));
    expect(theme.current).toBe("dracula");
    await user.hover(screen.getByRole("button", { name: "Nord" }));
    expect(theme.current).toBe("nord");
    // Yours is still the one marked while others are shown.
    expect(screen.getByRole("button", { name: "Mycelium dark" })).toHaveClass("text-accent");
    await user.unhover(screen.getByRole("group", { name: "Dark" }).parentElement!);
    expect(theme.current).toBe("dark");
  });

  it("keeps a clicked theme", async () => {
    const user = await openMenu();
    await user.hover(screen.getByRole("button", { name: "Dracula" }));
    await user.click(screen.getByRole("button", { name: "Dracula" }));
    expect(theme.current).toBe("dracula");
    expect(screen.queryByRole("button", { name: "Nord" })).not.toBeInTheDocument();
  });

  it("puts yours back when the menu is closed with Escape", async () => {
    const user = await openMenu();
    await user.hover(screen.getByRole("button", { name: "Solarized light" }));
    expect(theme.current).toBe("solarized-light");
    await user.keyboard("{Escape}");
    expect(theme.current).toBe("dark");
  });
});
