// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { X } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Checkbox } from "@/components/ui/checkbox";
import { useNotifications } from "@/components/notifications-provider";
import type { NotificationScope } from "@/lib/notifications";

interface Props {
  open: boolean;
  onClose: () => void;
}

const SCOPES: { id: NotificationScope; label: string; description: string }[] = [
  { id: "needs-me", label: "Needs me", description: "Mentions, direct messages, consensus, and knowledge writes." },
  { id: "everything", label: "Everything", description: "Also includes ambient activity, like agents joining a room." },
];

export function NotificationSettingsDialog({ open, onClose }: Props) {
  const { settings, setSettings, desktopPermission, requestDesktopPermission, unmuteRoom } = useNotifications();

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Notification settings</DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-5 py-1">
          <section>
            <div className="mb-2 text-micro font-semibold uppercase tracking-wide text-muted-foreground">Scope</div>
            <div className="flex flex-col gap-1.5">
              {SCOPES.map((s) => (
                <label
                  key={s.id}
                  className="flex cursor-pointer items-start gap-2.5 rounded-lg border border-border p-2.5 has-[:checked]:border-accent has-[:checked]:bg-accent-soft/30"
                >
                  <input
                    type="radio"
                    name="notification-scope"
                    className="sr-only"
                    checked={settings.scope === s.id}
                    onChange={() => setSettings({ ...settings, scope: s.id })}
                  />
                  <span
                    className="mt-0.5 flex size-3.5 flex-shrink-0 items-center justify-center rounded-full border"
                    style={{
                      borderColor: settings.scope === s.id ? "var(--accent)" : "var(--border2)",
                      background: settings.scope === s.id ? "var(--accent)" : "transparent",
                    }}
                    aria-hidden
                  />
                  <span className="min-w-0">
                    <div className="text-label font-medium text-text">{s.label}</div>
                    <div className="text-micro text-muted-foreground">{s.description}</div>
                  </span>
                </label>
              ))}
            </div>
          </section>

          <section className="flex flex-col gap-3">
            <div className="text-micro font-semibold uppercase tracking-wide text-muted-foreground">Delivery</div>

            <label className="flex items-center gap-2.5">
              <Checkbox
                checked={settings.dnd}
                onCheckedChange={(v) => setSettings({ ...settings, dnd: v === true })}
              />
              <span className="text-label text-text">Do not disturb (mute everything)</span>
            </label>

            <label className="flex items-center gap-2.5">
              <Checkbox
                checked={settings.soundEnabled}
                onCheckedChange={(v) => setSettings({ ...settings, soundEnabled: v === true })}
              />
              <span className="text-label text-text">Audio ping when the tab is hidden</span>
            </label>
            {settings.soundEnabled && (
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={settings.soundVolume}
                onChange={(e) => setSettings({ ...settings, soundVolume: Number(e.target.value) })}
                className="ml-6 w-[calc(100%-1.5rem)] accent-accent"
                aria-label="Sound volume"
              />
            )}

            <label className="flex items-center gap-2.5">
              <Checkbox
                checked={settings.desktopEnabled}
                onCheckedChange={(v) => {
                  const enabled = v === true;
                  setSettings({ ...settings, desktopEnabled: enabled });
                  if (enabled && desktopPermission === "default") requestDesktopPermission();
                }}
              />
              <span className="text-label text-text">Desktop notifications</span>
            </label>
            {settings.desktopEnabled && desktopPermission === "denied" && (
              <p className="ml-6 text-micro text-yellow">
                Blocked by the browser — allow notifications for this site to enable.
              </p>
            )}
            {settings.desktopEnabled && desktopPermission === "unsupported" && (
              <p className="ml-6 text-micro text-muted-foreground">Not supported in this browser.</p>
            )}
          </section>

          {settings.mutedRooms.length > 0 && (
            <section>
              <div className="mb-2 text-micro font-semibold uppercase tracking-wide text-muted-foreground">
                Muted rooms
              </div>
              <div className="flex flex-wrap gap-1.5">
                {settings.mutedRooms.map((room) => (
                  <span
                    key={room}
                    className="flex items-center gap-1 rounded-full border border-border px-2 py-0.5 text-micro text-muted-foreground"
                  >
                    {room}
                    <button
                      onClick={() => unmuteRoom(room)}
                      aria-label={`Unmute ${room}`}
                      className="text-faint hover:text-text"
                    >
                      <X className="size-3" />
                    </button>
                  </span>
                ))}
              </div>
            </section>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
