// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  APP_DOWNLOADS,
  appJoinLink,
  appPlatform,
  desktopMachine,
  desktopVersion,
  inviteLink,
  isDesktop,
  settingsLink,
  terminalLink,
  updateLink,
  useDesktopUpdate,
} from "@/lib/desktop";

describe("desktop links", () => {
  it("knows the app by its user agent", () => {
    const safari = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15";
    expect(isDesktop(safari)).toBe(false);
    expect(isDesktop(`${safari} MyceliumDesktop/0.1.0`)).toBe(true);
  });

  it("reads the app's version off the same mark", () => {
    const safari = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15";
    expect(desktopVersion(safari)).toBeNull();
    expect(desktopVersion(`${safari} MyceliumDesktop/3.0.14`)).toBe("3.0.14");
    expect(desktopVersion(`${safari} MyceliumDesktop/3.0.14-rc1`)).toBe("3.0.14-rc1");
  });

  it("asks the app for things by link, never by call", () => {
    expect(terminalLink("w9:p2")).toBe("mycelium://terminal?pane=w9%3Ap2");
    expect(settingsLink()).toBe("mycelium://settings");
    expect(appJoinLink("https://hub.example.com", "atlas")).toBe(
      "mycelium://join?hub=https%3A%2F%2Fhub.example.com&room=atlas",
    );
  });

  it("sends people an https link, which any chat app makes clickable", () => {
    expect(inviteLink("https://hub.example.com", "atlas migration")).toBe(
      "https://hub.example.com/join?room=atlas+migration",
    );
    expect(inviteLink("http://127.0.0.1:3717")).toBe("http://127.0.0.1:3717/join");
  });

  it("calls the machine a Mac on a Mac, and a computer elsewhere", () => {
    expect(desktopMachine("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) MyceliumDesktop/1.0")).toBe("Mac");
    expect(desktopMachine("Mozilla/5.0 (X11; Linux x86_64) MyceliumDesktop/1.0")).toBe("computer");
    expect(desktopMachine("Mozilla/5.0 (Windows NT 10.0; Win64; x64) MyceliumDesktop/1.0")).toBe("computer");
  });

  it("offers the app for the system a browser runs on, and none where it doesn't run", () => {
    const ua = {
      mac: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15",
      windows: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36",
      linux: "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36",
      android: "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/130.0 Mobile Safari/537.36",
      iphone: "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148",
      chromeos: "Mozilla/5.0 (X11; CrOS x86_64 15000.0.0) AppleWebKit/537.36 Chrome/130.0 Safari/537.36",
    };
    expect(appPlatform(ua.mac, 0)).toBe("Mac");
    // An iPad's Safari asks for the desktop site as a Mac; its touch screen gives it away.
    expect(appPlatform(ua.mac, 5)).toBeNull();
    expect(appPlatform(ua.windows, 0)).toBe("Windows");
    expect(appPlatform(ua.linux, 0)).toBe("Linux");
    expect(appPlatform(ua.android, 5)).toBeNull();
    expect(appPlatform(ua.iphone, 5)).toBeNull();
    expect(appPlatform(ua.chromeos, 0)).toBeNull();
    expect(APP_DOWNLOADS.Windows.url).toMatch(/\/Mycelium-windows-x86_64-setup\.exe$/);
    expect(APP_DOWNLOADS.Linux.url).toMatch(/\/Mycelium-linux-x86_64\.AppImage$/);
  });
});

describe("an update the app found", () => {
  const page = globalThis as { __myceliumUpdate?: unknown };
  const tell = (detail: unknown) => {
    page.__myceliumUpdate = detail;
    window.dispatchEvent(new CustomEvent("mycelium:update", { detail }));
  };

  afterEach(() => {
    delete page.__myceliumUpdate;
    vi.restoreAllMocks();
  });

  it("follows what the app says, inside the app", () => {
    vi.spyOn(navigator, "userAgent", "get").mockReturnValue("Mozilla/5.0 (Macintosh) MyceliumDesktop/3.0.33");
    const { result } = renderHook(() => useDesktopUpdate());
    expect(result.current).toBeNull();
    act(() => tell({ version: "3.0.34" }));
    expect(result.current).toBe("3.0.34");
    act(() => tell(null));
    expect(result.current).toBeNull();
    expect(updateLink()).toBe("mycelium://update");
  });

  it("says nothing in a browser, whatever the page holds", () => {
    page.__myceliumUpdate = { version: "3.0.34" };
    const { result } = renderHook(() => useDesktopUpdate());
    expect(result.current).toBeNull();
  });
});
