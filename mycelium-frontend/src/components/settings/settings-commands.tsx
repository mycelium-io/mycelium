// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useRouter } from "next/navigation";
import { useMemo } from "react";
import { useCommands } from "@/components/keymap-provider";
import { settingHref, type SettingsPage } from "@/lib/client-settings";
import { useHasAppSettings } from "@/lib/desktop-app";
import type { PaletteCommand } from "@/lib/commands";

/** Each settings page as a palette command, with the settings on it as words
 *  to find it by, so ⌘K → "time zone" lands on General. */
const PAGES: { page: SettingsPage; title: string; keywords: string[] }[] = [
  { page: "profile", title: "Profile", keywords: ["name", "handle", "who am i", "identity", "agents i own"] },
  { page: "general", title: "General", keywords: ["theme", "dark", "light", "send", "enter", "time zone", "export", "import"] },
  { page: "notifications", title: "Notifications", keywords: ["bell", "sound", "banner", "do not disturb", "mute"] },
  { page: "read-aloud", title: "Read aloud", keywords: ["speech", "speak", "voice", "tts", "kokoro", "listen"] },
  { page: "keys", title: "Keyboard shortcuts", keywords: ["keybindings", "keys", "hotkeys", "rebind"] },
  { page: "connection", title: "Connection", keywords: ["hub", "address", "switch hub", "invite", "join"] },
  { page: "room", title: "Room settings", keywords: ["room name", "private", "shared", "board moves", "worker turns", "dependencies"] },
  { page: "hub", title: "Hub", keywords: ["model", "api key", "workers", "sign-in", "voice", "usage"] },
];

/** The desktop app's own pages, there only in the app. */
const APP_PAGES: typeof PAGES = [
  { page: "model", title: "Engines' model", keywords: ["model", "engines", "api key", "provider", "anthropic", "openai", "ollama"] },
  { page: "agents", title: "Agents", keywords: ["folder", "working folder", "claude code", "codex", "herdr"] },
  { page: "voice", title: "Voice", keywords: ["mic", "microphone", "talk", "dictate", "speech model"] },
  { page: "experiences", title: "Experiences", keywords: ["patterns", "examples", "scenarios"] },
  { page: "privacy", title: "Privacy", keywords: ["usage stats", "analytics", "telemetry"] },
  { page: "version", title: "Version", keywords: ["update", "release candidate", "rc", "downgrade", "switch version"] },
  { page: "health", title: "Health check", keywords: ["doctor", "diagnose", "log", "problems"] },
];

/** Registers the settings pages with the command palette while mounted. */
export function SettingsCommands({ room }: { room?: string | null }) {
  const router = useRouter();
  const app = useHasAppSettings();
  const commands = useMemo<PaletteCommand[]>(
    () =>
      [...PAGES, ...(app ? APP_PAGES : [])].map(({ page, title, keywords }) => ({
        id: `settings.${page}`,
        title: `Settings: ${title}`,
        group: "Preferences",
        keywords: ["settings", "preferences", ...keywords],
        run: () => router.push(settingHref(page, undefined, page === "room" ? (room ?? undefined) : undefined)),
      })),
    [router, room, app],
  );
  useCommands(commands);
  return null;
}
