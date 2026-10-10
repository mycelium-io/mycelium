// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// The desktop app (Mycelium.app) shows this same UI in its window and marks
// its web view's user agent with `MyceliumDesktop/<version>`. The page never
// calls into the app: it asks for things by `mycelium://` link, which the app
// alone answers, so a hub's page can open an agent's terminal but can never
// run anything on the machine itself.

import { useSyncExternalStore } from "react";

const MARK = /\bMyceliumDesktop\/[\w.+-]+/;

export function isDesktop(userAgent: string = globalThis.navigator?.userAgent ?? ""): boolean {
  return MARK.test(userAgent);
}

/** The desktop app's own version, off the same mark, or null in a browser. */
export function desktopVersion(userAgent: string = globalThis.navigator?.userAgent ?? ""): string | null {
  return /\bMyceliumDesktop\/([\w.+-]+)/.exec(userAgent)?.[1] ?? null;
}

/** What copy calls the machine the app runs on: a Mac, or (Linux, Windows) a computer. */
export function desktopMachine(userAgent: string = globalThis.navigator?.userAgent ?? ""): "Mac" | "computer" {
  return /\bMacintosh\b/.test(userAgent) ? "Mac" : "computer";
}

const noSubscribe = () => () => {};

/** Whether this page is inside the desktop app. Always false while rendering on the server. */
export function useIsDesktop(): boolean {
  return useSyncExternalStore(noSubscribe, () => isDesktop(), () => false);
}

/**
 * A newer version of the app, when the app has found one it hasn't installed.
 * The app says so by setting `__myceliumUpdate` on the page and firing a
 * `mycelium:update` event (again on every page load), since the page never
 * calls into it. Null in a browser, and while rendering on the server.
 */
export function useDesktopUpdate(): string | null {
  return useSyncExternalStore(subscribeUpdate, readUpdate, () => null);
}

const UPDATE_EVENT = "mycelium:update";

function subscribeUpdate(onChange: () => void): () => void {
  globalThis.addEventListener?.(UPDATE_EVENT, onChange);
  return () => globalThis.removeEventListener?.(UPDATE_EVENT, onChange);
}

function readUpdate(): string | null {
  if (!isDesktop()) return null;
  const found = (globalThis as { __myceliumUpdate?: { version?: unknown } | null }).__myceliumUpdate;
  return typeof found?.version === "string" ? found.version : null;
}

/** Asks the app to update: its Check for Updates…, which asks before it downloads. */
export function updateLink(): string {
  return "mycelium://update";
}

/** Opens the app's agents terminal: at an agent's herdr pane, or where it was. */
export function terminalLink(pane?: string): string {
  return pane ? `mycelium://terminal?pane=${encodeURIComponent(pane)}` : "mycelium://terminal";
}

/** Opens the app's Settings window, where the app's own hub is set up. */
export function settingsLink(): string {
  return "mycelium://settings";
}

/** Opens the app joined to this hub, in a room. */
export function appJoinLink(hubUrl: string, room?: string | null): string {
  const params = new URLSearchParams({ hub: hubUrl });
  if (room) params.set("room", room);
  return `mycelium://join?${params}`;
}

/**
 * The link to send someone: an ordinary https page on this hub, since chat
 * apps and mail don't make `mycelium://` clickable. It opens the app when it
 * is installed and offers the download or the browser when it is not.
 */
export function inviteLink(hubUrl: string, room?: string | null): string {
  const url = new URL("/join", hubUrl);
  if (room) url.searchParams.set("room", room);
  return url.toString();
}

/** Where the app is downloaded from. */
export const DOWNLOAD_URL = "https://github.com/mycelium-io/mycelium/releases/latest";

const LATEST = `${DOWNLOAD_URL}/download`;

/** The app's disk image itself, for a one-click download on a Mac. */
export const DMG_URL = `${LATEST}/Mycelium-macos-arm64.dmg`;

/** The app for each system it runs on, one click each. */
export const APP_DOWNLOADS = {
  Mac: { platform: "Mac", url: DMG_URL },
  Windows: { platform: "Windows", url: `${LATEST}/Mycelium-windows-x86_64-setup.exe` },
  Linux: { platform: "Linux", url: `${LATEST}/Mycelium-linux-x86_64.AppImage` },
} as const;

export type AppDownload = (typeof APP_DOWNLOADS)[keyof typeof APP_DOWNLOADS];

/**
 * Which system a browser runs on, for the app to offer: none on a phone or a
 * tablet (an iPad's Safari says Macintosh, but has a touch screen) or on
 * ChromeOS, which the app doesn't run on.
 */
export function appPlatform(
  userAgent: string = globalThis.navigator?.userAgent ?? "",
  touchPoints: number = globalThis.navigator?.maxTouchPoints ?? 0,
): keyof typeof APP_DOWNLOADS | null {
  if (/Android|iPhone|iPad|iPod|CrOS/.test(userAgent)) return null;
  if (/Windows NT/.test(userAgent)) return "Windows";
  if (/Macintosh/.test(userAgent)) return touchPoints > 1 ? null : "Mac";
  if (/Linux|X11/.test(userAgent)) return "Linux";
  return null;
}

/** The app's download for this browser's system; null on the server and where it doesn't run. */
export function useAppDownload(): AppDownload | null {
  const platform = useSyncExternalStore(noSubscribe, () => appPlatform(), () => null);
  return platform ? APP_DOWNLOADS[platform] : null;
}
