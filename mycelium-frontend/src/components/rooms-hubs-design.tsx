// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

// DESIGN MOCKUP (local branch, not for merge). The rooms list for a computer
// that belongs to several hubs: "Your rooms" (this computer's, only you), then
// "Shared rooms", with the rooms you host here first and then one group per
// hub you've joined. The joined hubs and their rooms are made up.

import { Lock, Plus } from "lucide-react";
import type { ReactNode } from "react";
import { RoomAvatar } from "@/components/ui/room-avatar";

/** Picked on this computer, never sent by the hub; clear of the status hues. */
const JOINED: { name: string; color: string; status: ReactNode; dim?: boolean; rooms: { name: string; unread?: number }[] }[] = [
  {
    name: "work",
    color: "#7b93f0",
    status: <span className="text-green">●</span>,
    rooms: [{ name: "general", unread: 3 }, { name: "design-review" }, { name: "release" }],
  },
  { name: "studio", color: "#e38bc0", status: <span className="text-green">●</span>, rooms: [{ name: "sketches" }, { name: "crit" }] },
  { name: "sam", color: "#b48ce6", status: <span className="text-faint">can't reach</span>, dim: true, rooms: [{ name: "bikes" }] },
];

function Heading({ children }: { children: ReactNode }) {
  return <div className="mt-3 flex h-6 items-center px-1.5 text-micro font-medium text-faint first:mt-0">{children}</div>;
}

function HubHeading({ color, name, status }: { color?: string; name: string; status?: ReactNode }) {
  return (
    <div className="mt-1.5 flex h-6 items-center gap-1.5 px-1.5 text-micro text-muted-foreground">
      {color ? <span className="size-2 rounded-[2px]" style={{ background: color }} /> : <span className="size-2" />}
      <span>{name}</span>
      {status && <span className="ml-auto text-[11px]">{status}</span>}
    </div>
  );
}

/** A row for a room on another hub. It opens in that hub's own frame, so
 *  in this mockup it goes nowhere. */
function RemoteRow({ name, unread, dim }: { name: string; unread?: number; dim?: boolean }) {
  return (
    <div className={`group flex h-7 items-center gap-2 rounded px-1.5 hover:bg-hairline ${dim ? "opacity-50" : ""}`}>
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
  return (
    <>
      <Heading>
        <Lock className="mr-1.5 size-3" />
        Your rooms
      </Heading>
      {yours}
      <Heading>Shared rooms</Heading>
      <HubHeading name="Hosted here" status={<span className="text-faint">by invite</span>} />
      {hosted}
      {JOINED.map((hub) => (
        <div key={hub.name}>
          <HubHeading color={hub.color} name={hub.name} status={hub.status} />
          {hub.rooms.map((r) => (
            <RemoteRow key={r.name} name={r.name} unread={r.unread} dim={hub.dim} />
          ))}
        </div>
      ))}
      <a href="/settings/hubs" className="mt-2 flex h-7 items-center gap-2 rounded px-1.5 text-label text-faint hover:bg-hairline hover:text-text">
        <Plus className="size-3.5" /> Join another hub
      </a>
    </>
  );
}
