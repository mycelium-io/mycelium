// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState } from "react";
import Link from "next/link";
import { Bell, BellOff, Check, Settings, VolumeX, X } from "lucide-react";
import { Popover, PopoverTrigger, PopoverContent } from "@/components/ui/popover";
import { EmptyState } from "@/components/empty-state";
import { Tooltip } from "@/components/ui/tooltip";
import { useNotifications } from "@/components/notifications-provider";
import { NotificationSettingsDialog } from "@/components/notification-settings";
import type { NotificationKind } from "@/lib/notifications";

const KIND_LABEL: Record<NotificationKind, string> = {
  mention: "Mention",
  direct: "Direct",
  consensus: "Consensus",
  knowledge: "Knowledge",
  join: "Join",
  // Badge-only, filtered out of the bell — present for exhaustiveness.
  message: "Message",
};

const KIND_TONE: Record<NotificationKind, string> = {
  mention: "var(--accent)",
  direct: "var(--accent)",
  consensus: "var(--green)",
  knowledge: "var(--yellow)",
  join: "var(--muted-foreground)",
  message: "var(--muted-foreground)",
};

function timeAgo(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 60) return "now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.round(hours / 24)}d`;
}

export function NotificationBell() {
  const { notifications, unreadCount, settings, markRead, markAllRead, dismiss, clearAll, muteRoom } =
    useNotifications();
  const [open, setOpen] = useState(false);
  const [showSettings, setShowSettings] = useState(false);

  // The bell is the "loud" inbox: only alert items (mentions, directs, consensus,
  // knowledge). Badge-only room activity badges the sidebar, never lands here.
  const loud = notifications.filter((n) => n.alert !== false);
  const items = [...loud].reverse();

  // One string names the trigger and fills its tooltip, so the do-not-disturb
  // dot — too small to anchor a bubble of its own — is still readable and
  // announced.
  const bellLabel = [
    unreadCount > 0 ? `${unreadCount} unread notifications` : "Notifications",
    settings.dnd ? "do not disturb is on" : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <>
      <Popover open={open} onOpenChange={setOpen}>
        <Tooltip content={bellLabel}>
          <PopoverTrigger
            className="relative flex size-8 flex-shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-hairline hover:text-text"
            aria-label={bellLabel}
          >
            <Bell className="size-4" />
            {unreadCount > 0 && (
              <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-accent px-1 text-[10px] font-semibold tabular text-accent-fg">
                {unreadCount > 99 ? "99+" : unreadCount}
              </span>
            )}
            {settings.dnd && (
              <span
                aria-hidden
                className="absolute -bottom-0.5 -right-0.5 flex size-3 items-center justify-center rounded-full bg-surface text-muted-foreground"
              >
                <VolumeX className="size-2.5" />
              </span>
            )}
          </PopoverTrigger>
        </Tooltip>
        <PopoverContent className="flex max-h-[28rem] w-80 flex-col p-0">
          <div className="flex items-center gap-2 border-b border-border px-3 py-2.5">
            <span className="text-label font-semibold text-text">Notifications</span>
            <span className="text-micro tabular text-faint">{loud.length}</span>
            <div className="ml-auto flex items-center gap-1">
              {loud.length > 0 && (
                <Tooltip content="Mark all read">
                  <button
                    onClick={markAllRead}
                    aria-label="Mark all read"
                    className="flex size-6 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-hairline hover:text-text"
                  >
                    <Check className="size-3.5" />
                  </button>
                </Tooltip>
              )}
              <Tooltip content="Notification settings">
                <button
                  onClick={() => setShowSettings(true)}
                  aria-label="Notification settings"
                  className="flex size-6 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-hairline hover:text-text"
                >
                  <Settings className="size-3.5" />
                </button>
              </Tooltip>
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            {items.length === 0 ? (
              <EmptyState
                size="sm"
                icon={Bell}
                title="No notifications"
                description="Mentions, direct messages, and consensus show up here."
                className="py-8"
              />
            ) : (
              items.map((n) => (
                <div
                  key={n.id}
                  className={`group flex items-start gap-2 border-b border-border px-3 py-2.5 last:border-b-0 ${
                    n.read ? "" : "bg-accent-soft/40"
                  }`}
                >
                  <span
                    className="mt-1.5 size-1.5 flex-shrink-0 rounded-full"
                    style={{ background: n.read ? "transparent" : "var(--accent)" }}
                    aria-hidden
                  />
                  <Link
                    href={`/room/${encodeURIComponent(n.room)}`}
                    onClick={() => {
                      markRead(n.id);
                      setOpen(false);
                    }}
                    className="min-w-0 flex-1"
                  >
                    <div className="flex items-center gap-1.5">
                      <span
                        className="text-micro font-semibold uppercase tracking-wide"
                        style={{ color: KIND_TONE[n.kind] }}
                      >
                        {KIND_LABEL[n.kind]}
                      </span>
                      <span className="truncate text-micro text-muted-foreground">{n.room}</span>
                      <span className="ml-auto flex-shrink-0 text-micro tabular text-faint">{timeAgo(n.time)}</span>
                    </div>
                    <p className="mt-0.5 truncate text-label text-text">{n.summary || n.sender}</p>
                  </Link>
                  <div className="flex flex-shrink-0 items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
                    <Tooltip content={`Mute ${n.room}`}>
                      <button
                        onClick={(e) => {
                          e.preventDefault();
                          muteRoom(n.room);
                        }}
                        aria-label={`Mute ${n.room}`}
                        className="mt-0.5 flex size-5 items-center justify-center rounded text-faint hover:bg-hairline hover:text-text"
                      >
                        <BellOff className="size-3" />
                      </button>
                    </Tooltip>
                    <Tooltip content="Dismiss">
                      <button
                        onClick={(e) => {
                          e.preventDefault();
                          dismiss(n.id);
                        }}
                        aria-label="Dismiss"
                        className="mt-0.5 flex size-5 items-center justify-center rounded text-faint hover:bg-hairline hover:text-text"
                      >
                        <X className="size-3" />
                      </button>
                    </Tooltip>
                  </div>
                </div>
              ))
            )}
          </div>
          {loud.length > 0 && (
            <div className="border-t border-border px-3 py-1.5">
              <button onClick={clearAll} className="text-micro text-muted-foreground hover:text-text">
                Clear all
              </button>
            </div>
          )}
        </PopoverContent>
      </Popover>
      <NotificationSettingsDialog open={showSettings} onClose={() => setShowSettings(false)} />
    </>
  );
}
