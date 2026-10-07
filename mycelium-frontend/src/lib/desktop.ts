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

/** The Mac app's own version, off the same mark, or null in a browser. */
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

/** Opens an agent's herdr pane in the app's terminal window. */
export function terminalLink(pane: string): string {
  return `mycelium://terminal?pane=${encodeURIComponent(pane)}`;
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

/** The app's disk image itself, for a one-click download on a Mac. */
export const DMG_URL =
  "https://github.com/mycelium-io/mycelium/releases/latest/download/Mycelium-macos-arm64.dmg";
