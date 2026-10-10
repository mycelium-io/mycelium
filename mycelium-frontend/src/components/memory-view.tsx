// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ChevronLeft, Eye, FileQuestion, Pencil } from "lucide-react";
import { fetchMemory, fetchMemoryExpanded, type Memory } from "@/lib/api";
import { useRoomMemories, useRoomRevalidate } from "@/lib/room-data";
import { isLiveEpisode } from "@/lib/threads";
import { EmptyState } from "@/components/empty-state";
import { MemoryDetail } from "@/components/memory-detail";
import { MemoryEditor } from "@/components/memory-editor";
import { TaskDiscussion } from "@/components/task/task-discussion";
import { useCurrentUser } from "@/components/current-user";
import { useUnsavedGuard } from "@/components/unsaved-changes";
import { memoryEditPending, onMemoryEditRequest, takeMemoryEdit } from "@/lib/memory-edit-request";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip } from "@/components/ui/tooltip";

/** Asks before leaving a memory with unsaved edits; `proceed` runs once it's safe. */
export type GuardHandle = (proceed: () => void) => void;

/** How tall a body gets before it clamps, where a discussion follows it. The
 *  full page is where someone came to read, so it gives the body more room. */
const BODY_CLAMP_PX = { tab: 480, page: 720 } as const;

/**
 * One memory, drawn the same wherever it's opened: as a tab beside Channel,
 * Board and Network, or full page. A task (a memory with a thread) also shows
 * its discussion and its composer, and offers the room's verbs. Reading,
 * editing and the unsaved-edit guard all live here, so there is one place to
 * change how a memory looks.
 */
export function MemoryView({
  roomName,
  memoryKey,
  onOpenMemory,
  layout = "tab",
  onGuard,
}: {
  roomName: string;
  memoryKey: string;
  /** Opens a linked memory: another tab in the room, or another page. */
  onOpenMemory: (key: string) => void;
  /** `page` centres the memory and adds a way back to its room. */
  layout?: "tab" | "page";
  /** Hands the view's unsaved-edit guard up, so the room can ask before closing it. */
  onGuard?: (key: string, guard: GuardHandle | null) => void;
}) {
  const [memory, setMemory] = useState<Memory | null | undefined>(undefined);
  const [renderedBody, setRenderedBody] = useState<string | null>(null);
  // Opened from a right-click's Edit: start in the editor. Read in render,
  // consumed once mounted, so a second render can't lose it.
  const [editing, setEditing] = useState(() => memoryEditPending(memoryKey));
  useEffect(() => {
    takeMemoryEdit(memoryKey);
    return onMemoryEditRequest((key) => {
      if (key === memoryKey && takeMemoryEdit(key)) setEditing(true);
    });
  }, [memoryKey]);
  const { principal } = useCurrentUser();
  const revalidate = useRoomRevalidate(roomName);
  const { setDirty, guard, dialog: unsavedDialog } = useUnsavedGuard();

  // The room's memories revalidate on every write in the room, so a new
  // version of this one (saved here or anywhere else) shows without a reload.
  const { memories } = useRoomMemories(roomName);
  const listedVersion = memories.find(m => m.key === memoryKey)?.version;

  useEffect(() => {
    onGuard?.(memoryKey, guard);
    return () => onGuard?.(memoryKey, null);
  }, [memoryKey, guard, onGuard]);

  useEffect(() => {
    let live = true;
    fetchMemory(roomName, memoryKey).then(m => {
      if (live) setMemory(m);
    });
    fetchMemoryExpanded(roomName, memoryKey).then(exp => {
      if (live) setRenderedBody(exp.found && exp.rendered ? exp.rendered : null);
    });
    return () => {
      live = false;
    };
  }, [roomName, memoryKey, listedVersion]);

  const page = layout === "page";
  const centered = page ? "mx-auto w-full max-w-3xl" : undefined;
  const backToRoom = page ? (
    <Link
      href={`/room/${encodeURIComponent(roomName)}`}
      className="inline-flex items-center gap-1 text-micro text-muted-foreground transition-colors hover:text-accent"
    >
      <ChevronLeft className="size-3.5" />
      {roomName}
    </Link>
  ) : null;

  if (memory === undefined) {
    return (
      <div className={page ? "mx-auto w-full max-w-3xl space-y-3 px-6 py-10" : "space-y-3 px-6 py-6"}>
        <Skeleton className="h-3 w-40" />
        <Skeleton className="h-3 w-full max-w-prose" />
        <Skeleton className="h-3 w-3/4 max-w-prose" />
      </div>
    );
  }
  if (memory === null) {
    return (
      <div className="flex flex-col items-center gap-4 py-6">
        <EmptyState
          icon={FileQuestion}
          title={`No memory called ${memoryKey}`}
          description="It may have been deleted, or the link points at a key nobody wrote yet."
        />
        {backToRoom}
      </div>
    );
  }

  // Only a real thread has a discussion: a memory on the room's own live
  // episode (or none) is not a thread, and reading it as one would empty the
  // room's history.
  const hasDiscussion = Boolean(memory.episode) && !isLiveEpisode(roomName, memory.episode ?? "");
  // Following a link leaves this memory. When the view hands its guard up, the
  // room asks before leaving; otherwise (the full page) it asks here.
  const open = onGuard ? onOpenMemory : (key: string) => guard(() => onOpenMemory(key));

  // At the end of the memory's header, the same quiet button as its view
  // toggle.
  const actions = (
    <Tooltip content={editing ? "Back to the rendered memory" : "Edit this memory"}>
      <Button
        variant="ghost"
        size="xs"
        className="gap-1"
        aria-label={editing ? "View" : "Edit"}
        onClick={() => (editing ? guard(() => setEditing(false)) : setEditing(true))}
      >
        {editing ? <Eye className="size-3.5" /> : <Pencil className="size-3.5" />}
        <span className="hidden @2xl:inline">{editing ? "View" : "Edit"}</span>
      </Button>
    </Tooltip>
  );

  return (
    <div className="@container flex h-full min-h-0 flex-1 flex-col overflow-hidden bg-paper">
      <div className="min-h-0 flex-1 overflow-y-auto">
        {/* The toolbar spans the view, as every tab's does; a page centers
            what is under it. The app's breadcrumb already leads back to the room. */}
        <div className={page ? "pb-12" : undefined}>
          {editing ? (
            <MemoryEditor
              key={memory.key}
              memory={memory}
              roomName={roomName}
              actor={principal}
              onDirtyChange={setDirty}
              onNavigate={open}
              headerExtra={actions}
              onSaved={() => {
                // The room's memories revalidate, which brings the new version
                // (and its expanded body) back through the effect above.
                revalidate();
                setEditing(false);
                fetchMemory(roomName, memory.key).then(m => {
                  if (m) setMemory(m);
                });
              }}
              onCancel={() => guard(() => setEditing(false))}
            />
          ) : (
            <>
              <MemoryDetail
                memory={memory}
                roomName={roomName}
                onNavigate={open}
                variant="page"
                renderedBody={renderedBody}
                collapseBodyAt={hasDiscussion ? BODY_CLAMP_PX[layout] : null}
                bodyFade="paper"
                showKey
                actions={actions}
                bodyClassName={centered}
              />
              {hasDiscussion && memory.episode && (
                <div className={centered}>
                  <TaskDiscussion
                    roomName={roomName}
                    episode={memory.episode}
                    onOpenMemory={open}
                    className="px-6 md:px-8"
                  />
                </div>
              )}
            </>
          )}
        </div>
      </div>
      {unsavedDialog}
    </div>
  );
}
