// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import Link from "next/link";
import { X } from "lucide-react";
import { useNotifications } from "@/components/notifications-provider";
import { settingHref } from "@/lib/client-settings";
import { DEFAULT_SETTINGS, roomLevel } from "@/lib/notifications";
import type { SkipRule } from "@/lib/on-screen";
import { useIsDesktop } from "@/lib/desktop";
import { Note, Row, Section, Segmented, SettingsPage, Toggle } from "./settings-ui";

const PING_SKIPS: { value: SkipRule; label: string }[] = [
  { value: "thread", label: "Its thread is open" },
  { value: "room", label: "Its room is open" },
  { value: "never", label: "Never" },
];

/** How the bell tells you you've been mentioned, and which rooms are muted.
 *  The bell's gear opens this page, so there is one place to change them. */
export function NotificationsPage() {
  const { settings, setSettings, desktopPermission, requestDesktopPermission, unmuteRoom } = useNotifications();
  const desktop = useIsDesktop();
  const rooms = [...new Set([...settings.mutedRooms, ...Object.keys(settings.roomLevels ?? {})])]
    .filter((room) => roomLevel(settings, room) === "muted")
    .sort();

  return (
    <SettingsPage
      title="Notifications"
      scope={desktop ? "Saved in this app on this computer. Never sent to the hub." : "Saved in this browser. Never sent to the hub."}
    >
      <Section
        title="The bell"
        note="The bell lists messages that mention you by name (@ and your handle) or are sent to you, and nothing else. A silent mention (@~ and your handle) doesn't appear there."
      >
        <Row
          id="notifications.dnd"
          label="Do not disturb"
          help="Keep collecting mentions in the bell, without a sound or a banner."
          changed={settings.dnd}
          onReset={() => setSettings({ ...settings, dnd: false })}
          defaultLabel="off"
        >
          <Toggle label="Do not disturb" checked={settings.dnd} onChange={(dnd) => setSettings({ ...settings, dnd })} />
        </Row>
      </Section>

      <Section title="How">
        <Row
          id="notifications.sound"
          label="Sound"
          help="A short ping when someone mentions you, unless it's already in front of you (see below)."
          changed={settings.soundEnabled !== DEFAULT_SETTINGS.soundEnabled || settings.soundVolume !== DEFAULT_SETTINGS.soundVolume}
          onReset={() =>
            setSettings({ ...settings, soundEnabled: DEFAULT_SETTINGS.soundEnabled, soundVolume: DEFAULT_SETTINGS.soundVolume })
          }
          defaultLabel="on, half volume"
        >
          {settings.soundEnabled && (
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={settings.soundVolume}
              onChange={(e) => setSettings({ ...settings, soundVolume: Number(e.target.value) })}
              className="w-28 accent-accent"
              aria-label="Sound volume"
            />
          )}
          <Toggle
            label="Sound"
            checked={settings.soundEnabled}
            onChange={(soundEnabled) => setSettings({ ...settings, soundEnabled })}
          />
        </Row>
        <Row
          id="notifications.ping-skip"
          label="Quiet for what's in front of me"
          help="No ping for a mention you can already see. Choose what counts: its thread is open, its room is open, or never stay quiet."
          changed={settings.pingSkip !== DEFAULT_SETTINGS.pingSkip}
          onReset={() => setSettings({ ...settings, pingSkip: DEFAULT_SETTINGS.pingSkip })}
          defaultLabel="the room I have open"
        >
          <Segmented
            label="Quiet for what's in front of me"
            value={settings.pingSkip}
            options={PING_SKIPS}
            onChange={(pingSkip) => setSettings({ ...settings, pingSkip })}
          />
        </Row>
        <Row
          id="notifications.desktop"
          label="Banners"
          help="Your computer's own notification when someone mentions you while Mycelium isn't the window you're looking at."
          changed={settings.desktopEnabled !== DEFAULT_SETTINGS.desktopEnabled}
          onReset={() => setSettings({ ...settings, desktopEnabled: DEFAULT_SETTINGS.desktopEnabled })}
          defaultLabel="off"
          below={
            settings.desktopEnabled && desktopPermission === "denied" ? (
              <Note tone="error">The browser blocks notifications for this site. Allow them in its site settings.</Note>
            ) : settings.desktopEnabled && desktopPermission === "unsupported" ? (
              <Note>This browser can&apos;t show them.</Note>
            ) : null
          }
        >
          <Toggle
            label="Banners"
            checked={settings.desktopEnabled}
            onChange={(enabled) => {
              setSettings({ ...settings, desktopEnabled: enabled });
              if (enabled && desktopPermission === "default") requestDesktopPermission();
            }}
          />
        </Row>
        <Row
          id="notifications.read-aloud"
          label="Read aloud"
          help="Hearing messages read to you has its own settings: what it reads, what it skips and the voice."
        >
          <Link href={settingHref("read-aloud")} className="text-label text-accent hover:underline">
            Read aloud settings
          </Link>
        </Row>
      </Section>

      <Section
        title="Muted rooms"
        note="Mute a room from its … menu, or from its menu in the rooms list. Nothing from a muted room reaches the bell or badges the room."
      >
        {rooms.length === 0 ? (
          <Row label="None" help="No room is muted." />
        ) : (
          rooms.map((room) => {
            return (
              <Row key={room} label={room} help="Muted">
                <button
                  type="button"
                  onClick={() => unmuteRoom(room)}
                  aria-label={`Unmute ${room}`}
                  className="flex items-center gap-1 text-micro text-muted-foreground hover:text-text"
                >
                  <X className="size-3" />
                  Unmute
                </button>
              </Row>
            );
          })
        )}
      </Section>
    </SettingsPage>
  );
}
