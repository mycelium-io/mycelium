// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const theme = { current: "dark", set: vi.fn() };
vi.mock("next-themes", () => ({
  useTheme: () => ({
    theme: theme.current,
    resolvedTheme: theme.current,
    setTheme: (t: string) => {
      theme.current = t;
      theme.set(t);
    },
  }),
}));
vi.mock("@/components/keymap-provider", () => ({ useCommands: () => {} }));

import { ThemeToggle } from "@/components/theme-toggle";
import { __resetClientSettingsCache, setClientSetting } from "@/lib/client-settings";

const html = () => document.documentElement;

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
    theme.set.mockClear();
    // What next-themes painted for the chosen theme.
    html().className = "dark";
    html().removeAttribute("style");
  });

  it("paints a hovered theme without saving it, and takes it off when the pointer leaves", async () => {
    const user = await openMenu();
    await user.hover(screen.getByRole("button", { name: "Dracula" }));
    expect(html()).toHaveClass("theme-dracula");
    expect(html()).not.toHaveClass("dark");
    await user.hover(screen.getByRole("button", { name: "Nord" }));
    expect(html()).toHaveClass("theme-nord");
    expect(html()).not.toHaveClass("theme-dracula");
    // Nothing chosen, nothing written, so no other window sees it.
    expect(theme.set).not.toHaveBeenCalled();
    expect(window.localStorage.length).toBe(0);
    expect(screen.getByRole("button", { name: "Mycelium dark" })).toHaveClass("text-accent");

    await user.unhover(screen.getByRole("group", { name: "Dark" }).parentElement!);
    expect(html().className).toBe("dark");
  });

  it("keeps a clicked theme, the one write", async () => {
    const user = await openMenu();
    await user.hover(screen.getByRole("button", { name: "Dracula" }));
    await user.click(screen.getByRole("button", { name: "Dracula" }));
    expect(theme.set).toHaveBeenCalledExactlyOnceWith("dracula");
    expect(screen.queryByRole("button", { name: "Nord" })).not.toBeInTheDocument();
  });

  it("takes a preview off on Escape", async () => {
    const user = await openMenu();
    await user.hover(screen.getByRole("button", { name: "Solarized light" }));
    expect(html()).toHaveClass("theme-solarized-light");
    await user.keyboard("{Escape}");
    expect(html().className).toBe("dark");
    expect(theme.set).not.toHaveBeenCalled();
  });

  it("previews one of your own themes with its colors, and puts yours back", async () => {
    setClientSetting("appearance.custom-themes", [
      {
        id: "midnight",
        name: "Midnight",
        mode: "dark",
        colors: {
          bg: "#0c0e11", surface: "#14171c", paper: "#191d22", elevated: "#21262d",
          "muted-bg": "#21262d", text: "#e8ebee", "muted-foreground": "#a7adb5", faint: "#888f97",
          accent: "#5cc7d2", "accent-fg": "#06181b", green: "#4fc296", yellow: "#d9a94e", red: "#e6746f",
        },
      },
    ]);
    const user = await openMenu();
    await user.hover(screen.getByRole("button", { name: "Midnight" }));
    expect(html()).toHaveClass("theme-custom");
    expect(html().style.getPropertyValue("--accent")).not.toBe("");
    await user.keyboard("{Escape}");
    expect(html().className).toBe("dark");
    expect(html().style.getPropertyValue("--accent")).toBe("");
  });

  it("takes a keyboard preview off when focus leaves the menu", async () => {
    await openMenu();
    screen.getByRole("button", { name: "Nord" }).focus();
    expect(html()).toHaveClass("theme-nord");
    screen.getByRole("button", { name: "Theme" }).focus();
    expect(html().className).toBe("dark");
  });
});
