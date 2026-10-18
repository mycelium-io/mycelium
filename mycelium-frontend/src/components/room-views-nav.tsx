// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { Activity, CalendarClock, Folder, ListChecks, MessagesSquare, type LucideIcon } from "lucide-react";
import { KeyBadge } from "@/components/key-badge";
import { KbdChord } from "@/components/ui/kbd";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ROOM_VIEWS, VIEW_LABELS, type View } from "@/lib/room-dock";
import { cn } from "@/lib/utils";

/** The open room's views, as the Rooms rail draws them under the room. */
export interface RoomViewsNav {
  view: View;
  onView: (view: View) => void;
  /** The Channel's message count, shown on its row. */
  channelCount: number | null;
}

export const VIEW_ICONS: Record<View, LucideIcon> = {
  channel: MessagesSquare,
  stream: Activity,
  board: ListChecks,
  files: Folder,
  schedules: CalendarClock,
};

/**
 * Under the open room in the Rooms rail: its views, one row each, like a
 * folder's contents in a file tree. The one in the view pane is marked; each
 * row names its key on hover (⌘1 to ⌘5 in the desktop app).
 */
export function RoomViewsList({ view, onView, channelCount }: RoomViewsNav) {
  return (
    <nav aria-label="Room views" className="mb-1 flex flex-col">
      {ROOM_VIEWS.map(v => {
        const Icon = VIEW_ICONS[v];
        const current = v === view;
        return (
          <button
            key={v}
            type="button"
            aria-current={current ? "page" : undefined}
            data-tour={`tab-${v}`}
            onClick={() => onView(v)}
            className={cn(
              "group/view relative flex h-6 items-center gap-2 rounded pl-7 pr-1.5 text-left text-label transition-colors",
              current ? "bg-hairline text-text" : "text-muted-foreground hover:bg-hairline hover:text-text",
            )}
          >
            <Icon className="size-3.5 flex-shrink-0 text-faint" strokeWidth={1.8} />
            <span className="min-w-0 flex-1 truncate">{VIEW_LABELS[v]}</span>
            {v === "channel" && channelCount !== null && (
              <span className="text-micro tabular text-faint group-hover/view:hidden">{channelCount}</span>
            )}
            <span className="hidden group-hover/view:inline">
              <KbdChord action={`pane.${v}`} size="xs" tone="muted" />
            </span>
            <KeyBadge action={`pane.${v}`} />
          </button>
        );
      })}
    </nav>
  );
}

/**
 * The folded Rooms rail's version: the view's icon under the room's monogram,
 * opening the room's views as a menu.
 */
export function RoomViewMark({ view, onView }: RoomViewsNav) {
  const Icon = VIEW_ICONS[view];
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        aria-label={`${VIEW_LABELS[view]}. Change the view`}
        title={`${VIEW_LABELS[view]}. Change the view`}
        className="mt-1 flex size-6 items-center justify-center rounded text-muted-foreground outline-none transition-colors hover:bg-hairline hover:text-text focus-visible:bg-hairline data-[popup-open]:bg-hairline data-[popup-open]:text-text"
      >
        <Icon className="size-3.5" strokeWidth={1.8} />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-48">
        {ROOM_VIEWS.map(v => {
          const ItemIcon = VIEW_ICONS[v];
          return (
            <DropdownMenuItem key={v} onClick={() => onView(v)} aria-current={v === view || undefined}>
              <ItemIcon className="size-3.5 text-faint" />
              <span className={cn("min-w-0 flex-1", v === view && "font-medium")}>{VIEW_LABELS[v]}</span>
              <KbdChord action={`pane.${v}`} size="xs" tone="muted" />
            </DropdownMenuItem>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
