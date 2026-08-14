// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { primeAudio, type PingSound } from "@/lib/audio-ping";

/**
 * The audio-ping preferences: whether a hidden tab pings on room activity, how
 * broad a scope pings ("everything" vs. only what needs the acting-as
 * principal's attention), and the tone/volume. Locally persisted, same as the
 * acting-as identity it scopes against — there's no server-side account to
 * hang preferences off yet.
 */
const STORAGE_KEY = "mycelium.notify";

export type PingScope = "all" | "needs-me";

export interface NotificationSettings {
  enabled: boolean;
  scope: PingScope;
  sound: PingSound;
  volume: number;
}

const DEFAULTS: NotificationSettings = {
  enabled: false,
  scope: "needs-me",
  sound: "chime",
  volume: 0.5,
};

function isPingSound(v: unknown): v is PingSound {
  return v === "chime" || v === "ping" || v === "tone";
}

function load(): NotificationSettings {
  if (typeof window === "undefined") return DEFAULTS;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULTS;
    const parsed = JSON.parse(raw) as Partial<NotificationSettings>;
    return {
      enabled: typeof parsed.enabled === "boolean" ? parsed.enabled : DEFAULTS.enabled,
      scope: parsed.scope === "all" ? "all" : DEFAULTS.scope,
      sound: isPingSound(parsed.sound) ? parsed.sound : DEFAULTS.sound,
      volume: typeof parsed.volume === "number" ? Math.min(1, Math.max(0, parsed.volume)) : DEFAULTS.volume,
    };
  } catch {
    return DEFAULTS;
  }
}

interface NotificationSettingsContext {
  settings: NotificationSettings;
  update: (patch: Partial<NotificationSettings>) => void;
}

const Ctx = createContext<NotificationSettingsContext | null>(null);

export function NotificationSettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<NotificationSettings>(DEFAULTS);

  useEffect(() => {
    setSettings(load());
  }, []);

  const value = useMemo<NotificationSettingsContext>(
    () => ({
      settings,
      update: (patch) => {
        setSettings((prev) => {
          const next = { ...prev, ...patch };
          // Turning pinging on is the user gesture browsers require before
          // audio can play — unlock the AudioContext right here, not on the
          // first (possibly tab-hidden, gesture-less) ping.
          if (patch.enabled) primeAudio();
          if (typeof window !== "undefined") {
            window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
          }
          return next;
        });
      },
    }),
    [settings],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useNotificationSettings(): NotificationSettingsContext {
  const ctx = useContext(Ctx);
  if (!ctx) {
    throw new Error("useNotificationSettings must be used within a NotificationSettingsProvider");
  }
  return ctx;
}
