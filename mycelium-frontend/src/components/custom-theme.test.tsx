// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { act, render, waitFor } from "@testing-library/react";
import { SWRConfig } from "swr";
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

/** This machine's theme files, as the app's own server reads them. */
const files = {
  available: true,
  themes: [] as { id: string; name: string; mode: "light" | "dark"; colors: Record<string, string> }[],
  current: null as string | null,
  saved: [] as string[],
  reads: 0,
};
vi.mock("@/lib/api", () => ({
  fetchLocalThemes: async () => {
    files.reads += 1;
    return { available: files.available, themes: files.themes, current: files.current };
  },
  saveLocalTheme: async (id: string) => {
    files.saved.push(id);
    files.current = id;
    return id;
  },
  logFetchError: () => () => {},
}));

/** The held stream's `themes` feed: the app's server saying the files changed. */
const feed = { handlers: new Set<() => void>() };
const filesChanged = () => act(() => feed.handlers.forEach((h) => h()));
vi.mock("@/lib/stream-hub", async () => {
  const { useEffect } = await import("react");
  return {
    useThemeFilesStream: (handler: () => void) => {
      useEffect(() => {
        feed.handlers.add(handler);
        return () => void feed.handlers.delete(handler);
      }, [handler]);
    },
  };
});

import { ThemeFileSync } from "@/components/custom-theme";
import { __resetClientSettingsCache, getClientSetting } from "@/lib/client-settings";

const FERN = {
  id: "custom-fern",
  name: "Fern",
  mode: "dark" as const,
  colors: { bg: "#0f1a14", text: "#e6f2ea", accent: "#7ee0a1" },
};

function mount() {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <ThemeFileSync />
    </SWRConfig>,
  );
}

/** Long enough that a poll, if there were one, would have asked again. */
const idle = () => new Promise((r) => setTimeout(r, 2000));

describe("<ThemeFileSync />", () => {
  beforeEach(() => {
    window.localStorage.clear();
    __resetClientSettingsCache();
    theme.current = "dark";
    theme.set.mockClear();
    files.available = true;
    files.themes = [];
    files.current = null;
    files.saved = [];
    files.reads = 0;
  });

  it("reads the files once and asks nothing more while they don't change", async () => {
    mount();
    await idle();
    expect(files.reads).toBe(1);
  });

  it("reads them again when the app's server says they changed", async () => {
    mount();
    await waitFor(() => expect(files.reads).toBe(1));
    filesChanged();
    await waitFor(() => expect(files.reads).toBe(2));
  });

  it("switches to the theme theme.json names", async () => {
    files.current = "dracula";
    mount();
    await waitFor(() => expect(theme.set).toHaveBeenCalledWith("dracula"));
    expect(files.saved).toEqual([]);
  });

  it("follows `mycelium theme use` while the app is open", async () => {
    files.current = "dark";
    mount();
    await new Promise((r) => setTimeout(r, 50));
    files.current = "nord";
    filesChanged();
    await waitFor(() => expect(theme.set).toHaveBeenCalledWith("nord"));
    // Catching up isn't a pick of its own, so nothing is written back.
    expect(files.saved).toEqual([]);
  });

  it("switches to a theme an agent just added, once the app has read it", async () => {
    files.current = "dark";
    mount();
    await new Promise((r) => setTimeout(r, 50));
    files.themes = [FERN];
    files.current = "custom-fern";
    filesChanged();
    await waitFor(() => expect(theme.set).toHaveBeenCalledWith("custom"));
    expect(getClientSetting("appearance.custom-theme")).toBe("custom-fern");
  });

  it("writes the theme in use when theme.json names none yet", async () => {
    theme.current = "solarized-light";
    mount();
    await waitFor(() => expect(files.saved).toEqual(["solarized-light"]));
    expect(theme.set).not.toHaveBeenCalled();
  });

  it("does nothing where the app keeps no theme files", async () => {
    files.available = false;
    files.current = "nord";
    mount();
    await new Promise((r) => setTimeout(r, 50));
    expect(theme.set).not.toHaveBeenCalled();
    expect(files.saved).toEqual([]);
  });
});
