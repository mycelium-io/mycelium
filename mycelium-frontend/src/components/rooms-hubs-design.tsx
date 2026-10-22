// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

// DESIGN MOCKUP (local branch, not for merge). The rooms list for a computer
// that belongs to several hubs: "Your rooms" (this computer's, only for you),
// then "Shared rooms", with the rooms you host here first and then one group
// per hub you've joined. The joined hubs and their rooms are made up.
//
// No colour sets a hub apart. `?hubs=line` (the default) groups each hub the
// way folders are grouped: a heading that folds, its rooms under a thin line.
// `?hubs=initial` marks each hub with a grey tile of its first letter.

import { ChevronDown, Lock, Plus } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useState, type ReactNode } from "react";
import { RoomAvatar } from "@/components/ui/room-avatar";
import { cn } from "@/lib/utils";

const JOINED: { name: string; address: string; status?: ReactNode; dim?: boolean; rooms: { name: string; unread?: number }[] }[] = [
  { name: "work", address: "work.example.com", rooms: [{ name: "general", unread: 3 }, { name: "design-review" }, { name: "release" }] },
  { name: "studio", address: "studio.example.org", rooms: [{ name: "sketches" }, { name: "crit" }] },
  { name: "sam", address: "192.168.1.40", status: "can't reach", dim: true, rooms: [{ name: "bikes" }] },
];

type Style = "line" | "initial";

function Heading({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("mt-3 flex h-6 items-center px-1.5 text-micro font-medium text-faint first:mt-0", className)}>{children}</div>;
}

/** The hub's first letter on a grey tile, the same shape as a room's avatar. */
function Initial({ name }: { name: string }) {
  return (
    <span className="flex size-[18px] flex-shrink-0 items-center justify-center rounded-[4px] border border-border2 text-[10px] font-semibold uppercase text-muted-foreground">
      {name[0]}
    </span>
  );
}

function Hub({
  style,
  name,
  status,
  dim,
  children,
}: {
  style: Style;
  name: string;
  status?: ReactNode;
  dim?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(true);
  return (
    <div className="mt-1">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="group flex h-7 w-full items-center gap-1.5 rounded px-1.5 text-left hover:bg-hairline"
      >
        {style === "line" ? (
          <ChevronDown className={cn("size-3.5 flex-shrink-0 text-faint transition-transform", !open && "-rotate-90")} />
        ) : (
          <Initial name={name} />
        )}
        <span className="min-w-0 flex-1 truncate text-label font-medium text-text">{name}</span>
        {status && <span className="text-[11px] text-faint">{status}</span>}
      </button>
      {open && <div className={cn(style === "line" ? "ml-3 border-l border-border pl-1" : "pl-0", dim && "opacity-50")}>{children}</div>}
    </div>
  );
}

/** A row for a room on another hub. It opens in that hub's own frame, so
 *  in this mockup it goes nowhere. */
function RemoteRow({ name, unread }: { name: string; unread?: number }) {
  return (
    <div className="group flex h-7 items-center gap-2 rounded px-1.5 hover:bg-hairline">
      <RoomAvatar name={name} className="size-[18px] rounded-[4px] text-[8px]" />
      <span className={`min-w-0 flex-1 truncate text-label ${unread ? "font-medium text-text" : "text-muted-foreground group-hover:text-text"}`}>
        {name}
      </span>
      {unread ? (
        <span className="flex h-4 min-w-4 items-center justify-center rounded-full bg-accent px-1 text-[10px] font-semibold leading-none text-accent-fg">
          {unread}
        </span>
      ) : null}
    </div>
  );
}

export function HubGroupsDesign({ yours, hosted }: { yours: ReactNode; hosted: ReactNode }) {
  const style: Style = useSearchParams().get("hubs") === "initial" ? "initial" : "line";
  return (
    <>
      <Heading>
        <Lock className="mr-1.5 size-3" />
        Your rooms
      </Heading>
      {yours}
      <Heading className="mt-4">Shared rooms</Heading>
      <Hub style={style} name="Hosted here" status="by invite">
        {hosted}
      </Hub>
      {JOINED.map((hub) => (
        <Hub key={hub.name} style={style} name={hub.name} status={hub.status} dim={hub.dim}>
          {hub.rooms.map((r) => (
            <RemoteRow key={r.name} name={r.name} unread={r.unread} />
          ))}
        </Hub>
      ))}
      <a href="/settings/hubs" className="mt-2 flex h-7 items-center gap-2 rounded px-1.5 text-label text-faint hover:bg-hairline hover:text-text">
        <Plus className="size-3.5" /> Join another hub
      </a>
    </>
  );
}
