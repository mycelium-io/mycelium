// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * Opening an agent from its @ tag, anywhere in a room: the channel's "is
 * responding" line and the @ tags in messages. It opens the agent the way a
 * click in Members does, in the drawer that shows its terminal, live, when it
 * runs on this machine and says where it runs when it doesn't.
 *
 * Only agents that run in a terminal open. Engines and A2A members answer from
 * the hub and have no terminal, and a person has nothing to open yet, so their
 * @ tags stay plain, as Members leaves them.
 *
 *   <AgentOpenerProvider roomName="…">…</AgentOpenerProvider>
 *   const opener = useAgentOpener();   // null outside a room
 *   opener?.canOpen("builder") && opener.open("builder");
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { Responding } from "@/lib/activity";
import { useRoomRoster } from "@/lib/room-data";
import { AgentPeek, AgentScreenDrawer } from "@/components/agent-screen";

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

/** How long a pointer rests on a tag before its peek shows, so passing over a
 *  line of names doesn't flash a card for each. */
const PEEK_AFTER_MS = 350;
/** About the height of a peek: a tag nearer the top than this shows it below. */
const PEEK_ROOM_PX = 180;

/**
 * An @ tag that opens its agent: drawn as it always is, with a pointer and an
 * underline on hover and no button styling. Resting on it shows the last few
 * lines of the agent's terminal above it, when it runs on this machine. Plain
 * text when it opens nothing. `children` is what the tag shows (by default
 * `@handle`).
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
  const [peekAt, setPeekAt] = useState<DOMRect | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);
  const label = children ?? `@${bare(handle)}`;
  if (!opener?.canOpen(handle)) return className ? <span className={className}>{label}</span> : <>{label}</>;
  const name = bare(handle);
  const hide = () => {
    if (timer.current) clearTimeout(timer.current);
    setPeekAt(null);
  };
  return (
    <>
      <button
        type="button"
        onClick={(e) => {
          // A tag sits inside rows that react to clicks of their own.
          e.stopPropagation();
          hide();
          opener.open(handle);
        }}
        onPointerEnter={(e) => {
          const target = e.currentTarget;
          timer.current = setTimeout(() => setPeekAt(target.getBoundingClientRect()), PEEK_AFTER_MS);
        }}
        onPointerLeave={hide}
        aria-label={`Open @${name}`}
        className={`${className ?? ""} cursor-pointer rounded-sm decoration-1 underline-offset-2 hover:underline`}
      >
        {label}
      </button>
      {/* Above the page rather than inside the line: a message list scrolls
          and clips, and the peek must not be cut by it. */}
      {peekAt &&
        createPortal(
          <span
            className="pointer-events-none fixed z-50"
            // Above the tag, or below it when it's too near the top for the card.
            style={
              peekAt.top > PEEK_ROOM_PX
                ? { left: peekAt.left, bottom: window.innerHeight - peekAt.top + 6 }
                : { left: peekAt.left, top: peekAt.bottom + 6 }
            }
          >
            <AgentPeek room={opener.room} handle={name} />
          </span>,
          document.body,
        )}
    </>
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
