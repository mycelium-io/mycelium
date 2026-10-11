// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { X } from "lucide-react";
import { useNotifications } from "@/components/notifications-provider";
import { DEFAULT_SETTINGS, type NotificationScope, type RoomLevel } from "@/lib/notifications";
import { useIsDesktop } from "@/lib/desktop";
import { Note, Row, Section, Segmented, SettingsPage, Toggle } from "./settings-ui";

const LEVEL_LABEL: Record<RoomLevel, string> = {
  all: "Everything",
  mentions: "Only what needs me",
  muted: "Nothing",
};

/** What the bell tells you about, and how. These were the bell's own dialog;
 *  the bell's gear opens this page now, so there is one place to change them. */
export function NotificationsPage() {
  const { settings, setSettings, desktopPermission, requestDesktopPermission, unmuteRoom } = useNotifications();
  const desktop = useIsDesktop();
  const rooms = [
    ...new Set([...settings.mutedRooms, ...Object.keys(settings.roomLevels ?? {})]),
  ].sort();

  return (
    <SettingsPage
      title="Notifications"
      scope={desktop ? "Saved in this app on this computer. Never sent to the hub." : "Saved in this browser. Never sent to the hub."}
    >
      <Section title="Tell me about">
        <Row
          id="notifications.scope"
          label="What reaches the bell"
          help={
            settings.scope === "needs-me"
              ? "Mentions, direct messages, agreements reached, and memory written for you."
              : "All of that, plus the room's ambient activity, like agents joining."
          }
          changed={settings.scope !== DEFAULT_SETTINGS.scope}
          onReset={() => setSettings({ ...settings, scope: DEFAULT_SETTINGS.scope })}
          defaultLabel="what needs me"
        >
          <Segmented<NotificationScope>
            label="What reaches the bell"
            value={settings.scope}
            options={[
              { value: "needs-me", label: "What needs me" },
              { value: "everything", label: "Everything" },
            ]}
            onChange={(scope) => setSettings({ ...settings, scope })}
          />
        </Row>
        <Row
          id="notifications.dnd"
          label="Do not disturb"
          help="Keep collecting notifications in the bell, without a sound or a banner."
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
          help="A short ping when something arrives while Mycelium isn't the window you're looking at."
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
          id="notifications.desktop"
          label="Banners"
          help="Your computer's own notification, so you see it from another app."
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
      </Section>

      <Section
        title="Rooms set differently"
        note="Set a room from its menu in the rooms list. Rooms not listed here follow what reaches the bell."
      >
        {rooms.length === 0 ? (
          <Row label="None" help="Every room follows the setting above." />
        ) : (
          rooms.map((room) => {
            const level: RoomLevel = settings.roomLevels?.[room] ?? "muted";
            return (
              <Row key={room} label={room} help={LEVEL_LABEL[level]}>
                <button
                  type="button"
                  onClick={() => unmuteRoom(room)}
                  aria-label={`Let ${room} follow the setting above`}
                  className="flex items-center gap-1 text-micro text-muted-foreground hover:text-text"
                >
                  <X className="size-3" />
                  Clear
                </button>
              </Row>
            );
          })
        )}
      </Section>
    </SettingsPage>
  );
}
