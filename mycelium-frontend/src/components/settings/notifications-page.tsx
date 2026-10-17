// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { X } from "lucide-react";
import { useNotifications, useReadAloud } from "@/components/notifications-provider";
import { Button } from "@/components/ui/button";
import { DEFAULT_SETTINGS, roomLevel } from "@/lib/notifications";
import { useIsDesktop } from "@/lib/desktop";
import { Note, Row, Section, SettingsPage, Toggle } from "./settings-ui";

/** How the bell tells you you've been mentioned, and which rooms are muted.
 *  The bell's gear opens this page, so there is one place to change them. */
export function NotificationsPage() {
  const { settings, setSettings, desktopPermission, requestDesktopPermission, unmuteRoom } = useNotifications();
  const readAloud = useReadAloud();
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
          help="A short ping when someone mentions you, unless you're already looking at that room."
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
        {readAloud.available && (
          <Row
            id="notifications.read-aloud"
            label="Read aloud"
            help="Say who mentioned you and where, then the start of the message, with the words shown on the bell. Not while your mic is on, and not while Mycelium is hidden."
            changed={settings.readAloud !== DEFAULT_SETTINGS.readAloud}
            onReset={() => setSettings({ ...settings, readAloud: DEFAULT_SETTINGS.readAloud })}
            defaultLabel="off"
          >
            <Button size="sm" variant="outline" onClick={readAloud.tryIt} disabled={readAloud.state.item !== null}>
              Try it
            </Button>
            <Toggle
              label="Read aloud"
              checked={settings.readAloud}
              onChange={(readAloudOn) => setSettings({ ...settings, readAloud: readAloudOn })}
            />
          </Row>
        )}
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
