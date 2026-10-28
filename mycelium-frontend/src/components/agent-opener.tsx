// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * Opening an agent from its @ tag on the "is responding" line, in the channel
 * and in a task's thread; @ tags in messages stay plain text. It opens the
 * agent the way a click in Members does, in the drawer that shows its terminal,
 * live, when it runs on this machine and says where it runs when it doesn't.
 *
 * Only agents that run in a terminal open. Engines and A2A members answer from
 * the hub and have no terminal, and a person has nothing to open yet, so their
 * @ tags stay plain, as Members leaves them.
 *
 *   <AgentOpenerProvider roomName="…">…</AgentOpenerProvider>
 *   const opener = useAgentOpener();   // null outside a room
 *   opener?.canOpen("builder") && opener.open("builder");
 */

import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { Responding } from "@/lib/activity";
import { useRoomRoster } from "@/lib/room-data";
import { AgentScreenDrawer } from "@/components/agent-screen";
import { AgentCardHover } from "@/components/agent-card";

export interface AgentOpener {
  /** The room the tags are in. */
  room: string;
  /** Whether an @ tag for `handle` opens something. */
  canOpen: (handle: string) => boolean;
  open: (handle: string) => void;
}

const OpenerContext = createContext<AgentOpener | null>(null);

/** The room's opener, or null outside one (an @ tag is then plain text). */
export function useAgentOpener(): AgentOpener | null {
  return useContext(OpenerContext);
}

/** A handle as it's written in an @ tag: without its sigils, lowercased. */
function bare(handle: string): string {
  return handle.replace(/^@[~!]?/, "").toLowerCase();
}

export function AgentOpenerProvider({ roomName, children }: { roomName: string; children: React.ReactNode }) {
  const { agents } = useRoomRoster(roomName);
  const [opened, setOpened] = useState<{ handle: string; runner: string | null } | null>(null);

  // Engines and A2A members have no terminal to show, the same rule Members uses.
  const openable = useMemo(
    () =>
      new Map(
        agents
          .filter((a) => a.adapter !== "engine" && a.adapter !== "a2a")
          .map((a) => [a.handle.toLowerCase(), { handle: a.handle, runner: a.runner ?? null }]),
      ),
    [agents],
  );
  const canOpen = useCallback((handle: string) => openable.has(bare(handle)), [openable]);
  const open = useCallback(
    (handle: string) => {
      const found = openable.get(bare(handle));
      if (found) setOpened(found);
    },
    [openable],
  );
  const value = useMemo(() => ({ room: roomName, canOpen, open }), [roomName, canOpen, open]);

  return (
    <OpenerContext.Provider value={value}>
      {children}
      {opened && (
        <AgentScreenDrawer
          open
          onClose={() => setOpened(null)}
          room={roomName}
          handle={opened.handle}
          runner={opened.runner}
        />
      )}
    </OpenerContext.Provider>
  );
}

/**
 * An @ tag that opens its agent: drawn as it always is, with a pointer and an
 * underline on hover and no button styling. Resting on it shows the agent's
 * card above it (`AgentCardHover`), with its screen when it runs on this
 * machine. Plain text when it opens nothing. `children` is what the tag shows
 * (by default `@handle`).
 */
export function AgentTag({
  handle,
  className,
  children,
}: {
  handle: string;
  className?: string;
  children?: React.ReactNode;
}) {
  const opener = useAgentOpener();
  const label = children ?? `@${bare(handle)}`;
  if (!opener?.canOpen(handle)) return className ? <span className={className}>{label}</span> : <>{label}</>;
  const name = bare(handle);
  return (
    <AgentCardHover room={opener.room} handle={name} side="top">
      <button
        type="button"
        onClick={(e) => {
          // A tag sits inside rows that react to clicks of their own.
          e.stopPropagation();
          opener.open(handle);
        }}
        aria-label={`Open @${name}`}
        className={`${className ?? ""} cursor-pointer rounded-sm decoration-1 underline-offset-2 hover:underline`}
      >
        {label}
      </button>
    </AgentCardHover>
  );
}

/** Who is responding, "@x" / "@x and @y" / "@x, @y and 2 others", with each
 *  named @ tag opening its agent. */
export function RespondingNames({ group }: { group: Responding[] }) {
  const named = group.length > 2 ? group.slice(0, 2) : group;
  const more = group.length - named.length;
  return (
    <>
      {named.map((r, i) => (
        <span key={r.handle}>
          {i > 0 && (more > 0 ? ", " : " and ")}
          <AgentTag handle={r.handle} />
        </span>
      ))}
      {more > 0 && ` and ${more} ${more === 1 ? "other" : "others"}`}
    </>
  );
}
