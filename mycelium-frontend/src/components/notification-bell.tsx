// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useRef, useState } from "react";
import { Bell, BellOff } from "lucide-react";
import { useNotificationSettings, type PingScope } from "@/components/notification-settings";
import { PING_SOUNDS, playPing, primeAudio, type PingSound } from "@/lib/audio-ping";
import { Checkbox } from "@/components/ui/checkbox";

const SCOPE_OPTIONS: { value: PingScope; label: string; hint: string }[] = [
  { value: "needs-me", label: "Needs me", hint: "mentions, my agents, consensus" },
  { value: "all", label: "Everything", hint: "any room activity" },
];

const SOUND_LABELS: Record<PingSound, string> = {
  chime: "Chime",
  ping: "Ping",
  tone: "Tone",
};

/** Room-header control for the audio ping (issue #514): a short tone that
 *  plays on relevant room activity while the tab is hidden/unfocused. Never
 *  pings while the tab is visible — see the play trigger in event-stream.tsx. */
export function NotificationBell() {
  const { settings, update } = useNotificationSettings();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const Icon = settings.enabled ? Bell : BellOff;

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-label="Notification settings"
        title={settings.enabled ? "Audio ping on (hidden-tab activity)" : "Audio ping off"}
        onClick={() => setOpen((o) => !o)}
        className={`flex size-8 items-center justify-center rounded-md transition-colors hover:bg-surface hover:text-text ${
          settings.enabled ? "text-accent" : "text-muted-foreground"
        }`}
      >
        <Icon className="size-4" />
      </button>

      {open && (
        <div className="absolute right-0 top-full z-30 mt-1.5 w-64 rounded-xl border border-border bg-elevated p-3 shadow-xl">
          <label className="flex items-center justify-between gap-2">
            <span className="text-label font-medium text-text">Audio ping</span>
            <Checkbox
              checked={settings.enabled}
              onCheckedChange={(checked) => update({ enabled: checked === true })}
            />
          </label>
          <p className="mt-1 text-micro leading-relaxed text-muted-foreground">
            A short tone when the tab is hidden and something happens.
          </p>

          <div className={`mt-3 space-y-3 ${settings.enabled ? "" : "pointer-events-none opacity-40"}`}>
            <div className="space-y-1">
              <span className="text-micro font-medium text-muted-foreground">Scope</span>
              <div className="flex items-center gap-0.5 rounded-lg border border-border bg-surface p-0.5">
                {SCOPE_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    title={opt.hint}
                    onClick={() => update({ scope: opt.value })}
                    className={`flex-1 rounded-md px-2 py-1 text-label font-medium transition-colors ${
                      settings.scope === opt.value
                        ? "bg-elevated text-text shadow-sm ring-1 ring-border"
                        : "text-muted-foreground hover:bg-hairline hover:text-text"
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="space-y-1">
              <span className="text-micro font-medium text-muted-foreground">Sound</span>
              <div className="flex items-center gap-1.5">
                {PING_SOUNDS.map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => {
                      update({ sound: s });
                      primeAudio();
                      playPing(s, settings.volume);
                    }}
                    className={`flex-1 rounded-md border px-2 py-1 text-label font-medium transition-colors ${
                      settings.sound === s
                        ? "border-accent text-accent"
                        : "border-border text-muted-foreground hover:text-text"
                    }`}
                  >
                    {SOUND_LABELS[s]}
                  </button>
                ))}
              </div>
            </div>

            <label className="block space-y-1">
              <span className="text-micro font-medium text-muted-foreground">Volume</span>
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={settings.volume}
                onChange={(e) => update({ volume: Number(e.target.value) })}
                className="w-full accent-[var(--accent)]"
              />
            </label>
          </div>
        </div>
      )}
    </div>
  );
}
