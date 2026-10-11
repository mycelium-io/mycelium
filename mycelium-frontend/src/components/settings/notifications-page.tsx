// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { X } from "lucide-react";
import { useNotifications } from "@/components/notifications-provider";
import { DEFAULT_SETTINGS, type RoomLevel, type ToastSetting } from "@/lib/notifications";
import { entryTitle } from "@/lib/task-inbox";
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
  const { settings, setSettings, desktopPermission, requestDesktopPermission, unmuteRoom, unmuteTask, tasks } =
    useNotifications();
  const mutedTasks = settings.mutedTasks ?? [];
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
          id="notifications.toasts"
          label="Pop-ups"
          help={
            settings.toasts === "off"
              ? "No pop-ups. Tasks that need you still go to the bell."
              : "A small pop-up when a task needs you: someone asked you a question, a pull request is approved with CI passing, CI failed on your work, or your task is blocked."
          }
          changed={settings.toasts !== DEFAULT_SETTINGS.toasts}
          onReset={() => setSettings({ ...settings, toasts: DEFAULT_SETTINGS.toasts })}
          defaultLabel="when a task needs you"
        >
          <Segmented<ToastSetting>
            label="Pop-ups"
            value={settings.toasts}
            options={[
              { value: "your-move", label: "When a task needs you" },
              { value: "off", label: "Never" },
            ]}
            onChange={(toasts) => setSettings({ ...settings, toasts })}
          />
        </Row>
        <Row
          id="notifications.dnd"
          label="Do not disturb"
          help="Keep collecting notifications in the bell, without a pop-up, a sound or a banner."
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
          help="A short ping when a task needs you while Mycelium isn't the window you're looking at."
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
          help="Your computer's own notification when a task needs you, so you see it from another app."
          changed={settings.desktopEnabled !== DEFAULT_SETTINGS.desktopEnabled}
          onReset={() => setSettings({ ...settings, desktopEnabled: DEFAULT_SETTINGS.desktopEnabled })}
          defaultLabel="on"
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
        note="Set a room from its menu in the rooms list, or mute it from the room's … menu."
      >
        {rooms.length === 0 ? (
          <Row label="None" help="No room is set differently." />
        ) : (
          rooms.map((room) => {
            const level: RoomLevel = settings.roomLevels?.[room] ?? "muted";
            return (
              <Row key={room} label={room} help={LEVEL_LABEL[level]}>
                <button
                  type="button"
                  onClick={() => unmuteRoom(room)}
                  aria-label={`Clear the setting for ${room}`}
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

      <Section title="Muted tasks" note="Mute a task from its row's right-click menu on the board.">
        {mutedTasks.length === 0 ? (
          <Row label="None" help="Every task you're involved in reaches the bell." />
        ) : (
          mutedTasks.map((id) => {
            const task = tasks.find((t) => t.id === id);
            const title = task ? entryTitle(task) : id;
            return (
              <Row key={id} label={title} help={id.split("#")[0]}>
                <button
                  type="button"
                  onClick={() => unmuteTask(id)}
                  aria-label={`Unmute ${title}`}
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
