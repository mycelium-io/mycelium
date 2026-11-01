// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { fireEvent, render, screen } from "@testing-library/react";
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

import { CustomThemesRow } from "@/components/settings/custom-themes-row";
import { __resetClientSettingsCache, getClientSetting } from "@/lib/client-settings";

const COLORS = {
  bg: "#0c0e11",
  surface: "#14171c",
  paper: "#191d22",
  elevated: "#21262d",
  "muted-bg": "#21262d",
  text: "#e8ebee",
  "muted-foreground": "#a7adb5",
  faint: "#888f97",
  accent: "#5cc7d2",
  "accent-fg": "#06181b",
  green: "#4fc296",
  yellow: "#d9a94e",
  red: "#e6746f",
};

function paste(json: unknown) {
  // userEvent types `{` as a key descriptor, so the text goes in as one change.
  fireEvent.change(screen.getByRole("textbox", { name: "Theme JSON" }), {
    target: { value: typeof json === "string" ? json : JSON.stringify(json) },
  });
}

describe("<CustomThemesRow />", () => {
  beforeEach(() => {
    window.localStorage.clear();
    __resetClientSettingsCache();
    theme.current = "dark";
    theme.set.mockClear();
  });

  it("adds a pasted theme, switches to it and says it reads well", async () => {
    const user = userEvent.setup();
    render(<CustomThemesRow />);
    await user.click(screen.getByRole("button", { name: "Paste JSON" }));
    paste({ name: "Midnight", mode: "dark", colors: COLORS });
    await user.click(screen.getByRole("button", { name: "Add theme" }));

    expect(getClientSetting("appearance.custom-themes").map((t) => t.id)).toEqual(["custom-midnight"]);
    expect(getClientSetting("appearance.custom-theme")).toBe("custom-midnight");
    expect(theme.set).toHaveBeenCalledWith("custom");
    expect(screen.getByText(/Its words all read at 4.5:1 or better/)).toBeInTheDocument();
  });

  it("adds a hard-to-read theme but names what's hard to read", async () => {
    const user = userEvent.setup();
    render(<CustomThemesRow />);
    await user.click(screen.getByRole("button", { name: "Paste JSON" }));
    paste({ name: "Dim", mode: "dark", colors: { ...COLORS, faint: "#3a3f45" } });
    await user.click(screen.getByRole("button", { name: "Add theme" }));

    expect(getClientSetting("appearance.custom-themes")).toHaveLength(1);
    expect(screen.getByText(/faint text on the background: 1\.\d:1/)).toBeInTheDocument();
  });

  it("refuses a broken theme with its reasons and keeps nothing", async () => {
    const user = userEvent.setup();
    render(<CustomThemesRow />);
    await user.click(screen.getByRole("button", { name: "Paste JSON" }));
    paste({ name: "Typo", mode: "dark", colors: { ...COLORS, backround: "#000000" } });
    await user.click(screen.getByRole("button", { name: "Add theme" }));

    expect(screen.getByRole("alert")).toHaveTextContent(/"backround" isn't a color the app reads/);
    expect(getClientSetting("appearance.custom-themes")).toEqual([]);
    expect(theme.set).not.toHaveBeenCalled();
  });

  it("removes the theme showing and goes back to Mycelium dark", async () => {
    const user = userEvent.setup();
    render(<CustomThemesRow />);
    await user.click(screen.getByRole("button", { name: "Paste JSON" }));
    paste({ name: "Midnight", mode: "dark", colors: COLORS });
    await user.click(screen.getByRole("button", { name: "Add theme" }));
    await user.click(screen.getByRole("button", { name: "Remove Midnight" }));

    expect(getClientSetting("appearance.custom-themes")).toEqual([]);
    expect(getClientSetting("appearance.custom-theme")).toBe("");
    expect(theme.set).toHaveBeenLastCalledWith("dark");
  });
});
