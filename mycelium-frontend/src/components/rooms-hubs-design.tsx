// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

// DESIGN MOCKUP (local branch, not for merge). A computer that belongs to
// several hubs, the Discord way: a column of circles on the far left, one per
// hub, with this computer's own hub at the top. Choosing a hub shows only its
// rooms. The joined hubs and their rooms are made up.

import { Laptop, Plus } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { Tooltip } from "@/components/ui/tooltip";
import { RoomAvatar } from "@/components/ui/room-avatar";
import { cn } from "@/lib/utils";

export interface JoinedHub {
  id: string;
  address: string;
  you: string;
  open: boolean;
  down?: boolean;
  unread?: number;
  /** Messages there that ask you something; a number on the circle. */
  mentions?: number;
  rooms: { name: string; unread?: number }[];
}

export const JOINED: JoinedHub[] = [
  {
    id: "work",
    address: "work.example.com",
    you: "julia-v",
    open: true,
    unread: 3,
    mentions: 1,
    rooms: [{ name: "general", unread: 3 }, { name: "design-review" }, { name: "release" }],
  },
  { id: "studio", address: "studio.example.org", you: "julia", open: false, unread: 2, mentions: 1, rooms: [{ name: "sketches" }, { name: "crit" }] },
  { id: "sam", address: "192.168.1.40:8000", you: "julia", open: true, down: true, rooms: [{ name: "bikes" }] },
];

/** One hub's circle. The chosen one squares off a little and gets a bar at
 *  its left edge; one with unread messages gets a dot. */
function Circle({
  label,
  chosen,
  unread,
  mentions,
  dim,
  own,
  onClick,
  children,
}: {
  label: string;
  chosen: boolean;
  unread?: boolean;
  mentions?: number;
  dim?: boolean;
  /** This computer's own hub: an accent ring no joined hub can have. */
  own?: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <Tooltip content={label}>
      <button type="button" aria-label={label} aria-current={chosen || undefined} onClick={onClick} className="group relative flex w-full justify-center">
        <span
          className={cn(
            "absolute left-0 top-1/2 w-1 -translate-y-1/2 rounded-r bg-text transition-all",
            chosen ? "h-6" : unread ? "h-1.5" : "h-0 group-hover:h-3",
          )}
        />
        <span
          className={cn(
            "relative flex size-9 items-center justify-center border text-label font-semibold transition-all",
            chosen ? "rounded-xl bg-elevated text-text" : "rounded-full bg-surface text-muted-foreground group-hover:rounded-xl group-hover:text-text",
            own ? "border-accent/60 text-accent" : chosen ? "border-border2" : "border-border",
            dim && "opacity-45",
          )}
        >
          {children}
          {mentions ? (
            <span className="absolute -bottom-1 -right-1 flex h-4 min-w-4 items-center justify-center rounded-full border-2 border-[var(--bg)] bg-accent px-1 text-[10px] font-semibold leading-none text-accent-fg">
              {mentions}
            </span>
          ) : null}
        </span>
      </button>
    </Tooltip>
  );
}

/** The column of hubs at the far left of the rooms list. */
export function HubRail({ hub, onHub }: { hub: string; onHub: (id: string) => void }) {
  return (
    <nav aria-label="Hubs" className="flex w-[52px] flex-shrink-0 flex-col items-center gap-2 border-r border-border py-2.5">
      <Circle label="This computer · your own hub" own chosen={hub === "local"} onClick={() => onHub("local")}>
        <Laptop className="size-4" />
      </Circle>
      <span className="my-0.5 h-px w-6 bg-border" />
      {JOINED.map((h) => (
        <Circle
          key={h.id}
          label={`${h.address}${h.down ? " · can't reach" : ""}`}
          chosen={hub === h.id}
          unread={!!h.unread}
          mentions={h.mentions}
          dim={h.down}
          onClick={() => onHub(h.id)}
        >
          {h.id[0].toUpperCase() + h.id[1]}
        </Circle>
      ))}
      <Tooltip content="Join another hub">
        <Link
          href="/settings/hubs"
          aria-label="Join another hub"
          className="flex size-9 items-center justify-center rounded-full border border-dashed border-border2 text-faint transition-all hover:rounded-xl hover:text-text"
        >
          <Plus className="size-4" />
        </Link>
      </Tooltip>
    </nav>
  );
}

/** The rooms of a hub you've joined. In the real app they open in that hub's
 *  own frame; here they go nowhere. */
export function JoinedHubRooms({ hub }: { hub: JoinedHub }) {
  return (
    <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
      <div className="mb-1 flex h-8 flex-shrink-0 items-center gap-2 border-b border-border bg-surface px-3">
        <span className="min-w-0 truncate text-micro font-medium text-text">{hub.address}</span>
        {hub.down && <span className="ml-auto flex-shrink-0 whitespace-nowrap text-micro text-faint">can't reach</span>}
      </div>
      <p className="px-3 pb-2 pt-1 text-micro leading-relaxed text-faint">
        You're @{hub.you} here.{" "}
        {hub.down ? "Showing what was loaded 2 hours ago." : hub.open ? "It doesn't check who people are." : "Only people it invited can get in."}
      </p>
      <nav className={cn("px-2", hub.down && "opacity-50")}>
        {hub.rooms.map((r) => (
          <div key={r.name} className="group flex h-7 items-center gap-2 rounded px-1.5 hover:bg-hairline">
            <RoomAvatar name={r.name} className="size-[18px] rounded-[4px] text-[8px]" />
            <span className={cn("min-w-0 flex-1 truncate text-label", r.unread ? "font-medium text-text" : "text-muted-foreground group-hover:text-text")}>
              {r.name}
            </span>
            {r.unread ? (
              <span className="flex h-4 min-w-4 items-center justify-center rounded-full bg-accent px-1 text-[10px] font-semibold leading-none text-accent-fg">
                {r.unread}
              </span>
            ) : null}
          </div>
        ))}
      </nav>
    </div>
  );
}
