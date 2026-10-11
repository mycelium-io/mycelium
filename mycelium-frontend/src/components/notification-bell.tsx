// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState } from "react";
import Link from "next/link";
import { Bell, Check, Settings, VolumeX, X } from "lucide-react";
import { Popover, PopoverTrigger, PopoverContent } from "@/components/ui/popover";
import { EmptyState } from "@/components/empty-state";
import { Tooltip } from "@/components/ui/tooltip";
import { iconButtonClass } from "@/components/ui/icon-button";
import { useNotifications } from "@/components/notifications-provider";
import { settingHref } from "@/lib/client-settings";
import type { StoredNotification } from "@/lib/notifications";
import { threadShortId } from "@/lib/threads";

/** The first non-blank line, so a long message reads as one line. */
const firstLine = (text: string) => text.split("\n").find((l) => l.trim())?.trim() ?? "";

/** Where a mention opens: its task's thread, or the channel at the message. */
function mentionHref(n: StoredNotification): string {
  const room = `/room/${encodeURIComponent(n.room)}`;
  const short = threadShortId(n.episode);
  const focus = short ? `episode:${short}` : `message:${n.id}`;
  return `${room}?focus=${encodeURIComponent(focus)}`;
}

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
  const { notifications, unreadCount, settings, markRead, markAllRead, dismiss, clearAll } = useNotifications();
  const [open, setOpen] = useState(false);

  // The bell holds messages that mention you (or were sent to you), and
  // nothing else. Other room activity only badges the room in the sidebar.
  const loud = notifications.filter((n) => n.alert !== false && n.needsMe);
  const items = [...loud].reverse();

  // One string names the trigger and fills its tooltip, so the do-not-disturb
  // dot — too small to anchor a bubble of its own — is still readable and
  // announced.
  const bellLabel = [
    unreadCount > 0 ? `${unreadCount} unread mention${unreadCount === 1 ? "" : "s"}` : "Mentions",
    settings.dnd ? "do not disturb is on" : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <>
      <Popover open={open} onOpenChange={setOpen}>
        <Tooltip content={bellLabel}>
          <PopoverTrigger
            className={iconButtonClass("md", "relative data-[popup-open]:bg-hairline data-[popup-open]:text-text")}
            aria-label={bellLabel}
          >
            <Bell />
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
            <span className="text-label font-semibold text-text">Mentions</span>
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
                <Link
                  href={settingHref("notifications")}
                  onClick={() => setOpen(false)}
                  aria-label="Notification settings"
                  className="flex size-6 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-hairline hover:text-text"
                >
                  <Settings className="size-3.5" />
                </Link>
              </Tooltip>
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            {items.length === 0 ? (
              <EmptyState
                size="sm"
                icon={Bell}
                title="No mentions"
                description="When someone writes @ and your handle, the message shows up here and plays a sound."
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
                    href={mentionHref(n)}
                    onClick={() => {
                      markRead(n.id);
                      setOpen(false);
                    }}
                    className="min-w-0 flex-1"
                  >
                    <div className="flex items-center gap-1.5">
                      <span className="flex-shrink-0 text-micro font-semibold text-text">{n.sender}</span>
                      <span className="truncate text-micro text-muted-foreground">
                        {n.room} · {n.title ?? (n.episode ? "a thread" : "channel")}
                      </span>
                      <span className="ml-auto flex-shrink-0 text-micro tabular text-faint">{timeAgo(n.time)}</span>
                    </div>
                    <p className="mt-0.5 truncate text-label text-text">{firstLine(n.summary)}</p>
                  </Link>
                  <div className="flex flex-shrink-0 items-center gap-0.5 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
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
    </>
  );
}
