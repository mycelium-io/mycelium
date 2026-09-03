// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Eye, Maximize2, MessageSquare, Pencil, X } from "lucide-react";
import { memoryHref } from "@/lib/memory-routes";
import { useRoomEpisodes, useRoomMembers, useRoomMemories, useRoomRevalidate } from "@/lib/room-data";
import { threadShortId } from "@/lib/threads";
import { FlowPanel } from "@/components/flow-panel";
import { MemoryDetail } from "@/components/memory-detail";
import { MemoryEditor } from "@/components/memory-editor";
import { RoomChatBox } from "@/components/room-chat-box";
import { TaskConversation } from "@/components/task/task-conversation";
import { useCurrentUser } from "@/components/current-user";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Kbd } from "@/components/ui/kbd";
import { Tooltip } from "@/components/ui/tooltip";

/** How tall a task body gets in the pane before it clamps. The pane is narrow,
 *  so this is roughly a screenful of prose — enough to read the task, not enough
 *  to bury the conversation under it. */
const BODY_CLAMP_PX = 320;

/** What a thread is a thread *of*, as far as anything can tell. */
export interface ThreadTarget {
  /** The episode URN the conversation is tagged with. */
  episode: string;
  /**
   * The task this thread belongs to, when the room knows. A coordination phase
   * opens its own episode and records no back-link to the task that summoned
   * it, so this is absent for one — the pane says which thread rather than
   * inventing which task.
   */
  title?: string | null;
}

interface Props {
  roomName: string;
  target: ThreadTarget;
  onClose: () => void;
  /** A `[[wikilink]]` in a thread message opens the memory, same as in chat. */
  onOpenMemory?: (key: string) => void;
}

/**
 * One task's conversation, on its own.
 *
 * A **transient pane**, not a rail: it is here because you opened a row and
 * gone when you close it, and the room keeps no chrome for it in between —
 * the same restraint that keeps skills out of a rail of their own. There is
 * deliberately no "all threads" view either: a thread is reached through the
 * task it belongs to, which is the only place it means anything.
 *
 * The pane composes the shared parts a task has everywhere it is shown: the
 * task itself as {@link MemoryDetail} (or {@link MemoryEditor} when editing),
 * the {@link TaskConversation} below it, and the room's composer pointed at
 * this episode. The read is the conversation's own SWR entry, so opening this
 * never replaces the room's feed with a filtered slice of itself.
 */
export function ThreadView({ roomName, target, onClose, onOpenMemory }: Props) {
  // The task this thread is of, resolved by its episode — the row is the thread,
  // so the pane opens with the task itself (its body and fields) above the
  // conversation about it, the way an issue shows its description over its
  // comments. Absent for a negotiation thread bound to no row.
  const { memories } = useRoomMemories(roomName);
  const task = memories.find(m => m.episode === target.episode) ?? null;
  // A thread that is a run carries its flow on its episode record; the floor
  // held on it is a live fact off the roster. Absent for a task's own thread
  // and for a negotiation, so the pane draws nothing extra there.
  const { episodes } = useRoomEpisodes(roomName);
  const run = episodes.find(e => e.episode === target.episode && e.flow) ?? null;
  const { floors } = useRoomMembers(roomName);
  const floor = floors.find(f => f.episode === target.episode) ?? null;
  const { principal } = useCurrentUser();
  const revalidate = useRoomRevalidate(roomName);
  const shortId = threadShortId(target.episode) ?? "thread";
  const [isEditing, setIsEditing] = useState(false);

  // The conversation owns the read; it hands us its refresh so a send through
  // the composer below can re-read the episode.
  const refreshRef = useRef<(() => void) | null>(null);
  const onReady = useCallback((refresh: () => void) => {
    refreshRef.current = refresh;
  }, []);
  const refresh = useCallback(() => refreshRef.current?.(), []);

  // Esc closes: the pane is transient, so leaving it must be as cheap as
  // opening it was.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      const el = e.target as HTMLElement | null;
      if (el && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)) return;
      onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <section
      aria-label={`Thread ${shortId}`}
      data-thread={target.episode}
      // min-w-0 + overflow-hidden so the pane shrinks to its panel track rather
      // than letting content set a floor and spill under the inspector rail —
      // the same bounding the room surface has. Without it a wide message or a
      // long metadata value pushes the whole section past its right edge.
      className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-bg"
    >
      <header className="flex h-[48px] shrink-0 items-center gap-2 border-b border-border bg-paper px-4">
        <MessageSquare className="size-3.5 shrink-0 text-accent" strokeWidth={1.9} />
        <span className="min-w-0 truncate text-label font-semibold text-text">
          {target.title || (run ? `${run.flow?.name} run ${shortId}` : `Thread ${shortId}`)}
        </span>
        {/* The short id only where a task's name is what the header says —
            otherwise the header is already the id, and this would repeat it. */}
        {target.title && (
          <Tooltip content={target.episode}>
            {/* And only where the header is not already down to four characters
                of that name: on a phone the pane is the window, and the title
                is what says which task the window is. */}
            <span className="hidden shrink-0 rounded bg-hairline px-1.5 py-px font-mono text-micro text-muted-foreground sm:inline">
              {shortId}
            </span>
          </Tooltip>
        )}
        <span className="ml-auto flex items-center gap-2">
          {/* Edit the task in place, only where the pane is a task. A plain
              toggle with a revalidate on save: the pane is narrow and transient,
              so it keeps less chrome than the full page does. */}
          {task && (
            <Tooltip content={isEditing ? "View task" : "Edit task"}>
              <button
                type="button"
                onClick={() => setIsEditing(v => !v)}
                aria-label={isEditing ? "View task" : "Edit task"}
                className="grid size-6 place-items-center rounded text-muted-foreground transition-colors hover:bg-hairline hover:text-text"
              >
                {isEditing ? <Eye className="size-3.5" strokeWidth={1.9} /> : <Pencil className="size-3.5" strokeWidth={1.9} />}
              </button>
            </Tooltip>
          )}
          {/* Full screen: leave the split and open the task on its own page —
              the same memory, room to work. Only where the pane is a task (a
              negotiation thread has no page of its own to open). */}
          {task && (
            <Tooltip content="Open full screen">
              <Link
                href={memoryHref(roomName, task.key)}
                aria-label="Open task full screen"
                className="grid size-6 place-items-center rounded text-muted-foreground transition-colors hover:bg-hairline hover:text-text"
              >
                <Maximize2 className="size-3.5" strokeWidth={1.9} />
              </Link>
            </Tooltip>
          )}
          {/* The key that does what the ✕ beside it does — worth the width on a
              keyboard, and worth none of it on a phone. */}
          <Kbd size="xs" tone="muted" className="hidden sm:inline-flex">Esc</Kbd>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close thread"
            className="grid size-6 place-items-center rounded text-muted-foreground transition-colors hover:bg-hairline hover:text-text"
          >
            <X className="size-3.5" strokeWidth={1.9} />
          </button>
        </span>
      </header>

      {task && isEditing ? (
        // The editor owns its own scroll; it replaces the body and stands in
        // for the conversation while a save is in flight.
        <div className="min-h-0 flex-1 overflow-y-auto">
          <MemoryEditor
            key={task.key}
            memory={task}
            roomName={roomName}
            actor={principal}
            onSaved={() => {
              revalidate();
              setIsEditing(false);
            }}
            onCancel={() => setIsEditing(false)}
          />
        </div>
      ) : (
        // The task's body over its conversation, in one scroll. The body is
        // clamped rather than boxed: a long task fades under an Expand button
        // instead of taking a scrollbar of its own, so the wheel does one thing
        // everywhere in the pane. A negotiation thread bound to no row is all
        // conversation.
        <ScrollArea className="min-h-0 flex-1">
          {run && (
            <div className="border-b border-border">
              <FlowPanel episode={run} floor={floor} />
            </div>
          )}
          {task && (
            <div className="border-b border-border">
              <MemoryDetail
                memory={task}
                roomName={roomName}
                variant="rail"
                onNavigate={onOpenMemory}
                collapseBodyAt={BODY_CLAMP_PX}
              />
            </div>
          )}
          <TaskConversation
            roomName={roomName}
            episode={target.episode}
            onOpenMemory={onOpenMemory}
            onReady={onReady}
          />
        </ScrollArea>
      )}

      <RoomChatBox
        roomName={roomName}
        episode={target.episode}
        threadLabel={target.title || shortId}
        onSent={refresh}
      />
    </section>
  );
}
