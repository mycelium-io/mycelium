// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Eye, FileQuestion, Pencil } from "lucide-react";
import { fetchMemory, fetchMemoryExpanded, type Memory } from "@/lib/api";
import { useRoomMemories, useRoomRevalidate } from "@/lib/room-data";
import { isLiveEpisode } from "@/lib/threads";
import { EmptyState } from "@/components/empty-state";
import { MemoryDetail } from "@/components/memory-detail";
import { MemoryEditor } from "@/components/memory-editor";
import { RoomChatBox } from "@/components/room-chat-box";
import { TaskConversation } from "@/components/task/task-conversation";
import { useCurrentUser } from "@/components/current-user";
import { useUnsavedGuard } from "@/components/unsaved-changes";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip } from "@/components/ui/tooltip";

/** A long body is clamped where a discussion follows it, so the discussion stays in reach. */
const BODY_CLAMP_PX = 480;

/** Remembers the unsaved-edit guard of every open memory tab, so closing or
 *  leaving one with edits in progress asks first. */
export type GuardHandle = (proceed: () => void) => void;

/**
 * One memory, open as a tab beside Channel, Board and Network: read where there
 * is room to read it, while the rail keeps the tree. Editing, its links and its
 * discussion live here, as they did in the drawer this replaces.
 */
export function MemoryTab({
  roomName,
  memoryKey,
  onOpenMemory,
  onGuard,
}: {
  roomName: string;
  memoryKey: string;
  onOpenMemory: (key: string) => void;
  /** Hands the tab's unsaved-edit guard up, so the page can ask before closing it. */
  onGuard?: (key: string, guard: GuardHandle | null) => void;
}) {
  const [memory, setMemory] = useState<Memory | null | undefined>(undefined);
  const [renderedBody, setRenderedBody] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const { principal } = useCurrentUser();
  const revalidate = useRoomRevalidate(roomName);
  const { setDirty, guard, dialog: unsavedDialog } = useUnsavedGuard();

  // The tree revalidates on every memory write in the room; a new version of
  // this memory shows here without a reload.
  const { memories } = useRoomMemories(roomName);
  const listed = memories.find(m => m.key === memoryKey);
  const listedVersion = listed?.version;

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

  // The discussion refreshes itself when a message is sent from its composer.
  const threadRefresh = useRef<(() => void) | null>(null);
  const onThreadReady = useCallback((refresh: () => void) => {
    threadRefresh.current = refresh;
  }, []);

  if (memory === undefined) {
    return (
      <div className="space-y-3 px-6 py-6">
        <Skeleton className="h-3 w-40" />
        <Skeleton className="h-3 w-full max-w-prose" />
        <Skeleton className="h-3 w-3/4 max-w-prose" />
      </div>
    );
  }
  if (memory === null) {
    return (
      <EmptyState
        icon={FileQuestion}
        title={`No memory called ${memoryKey}`}
        description="It may have been deleted, or the link points at a key nobody wrote yet."
      />
    );
  }

  // Only a real thread has a discussion: a memory on the room's own live
  // episode (or none) is not a thread, and reading it as one would empty the
  // room's history.
  const hasDiscussion = Boolean(memory.episode) && !isLiveEpisode(roomName, memory.episode ?? "");

  // Edit, at the end of its one meta line. The tab is the memory's page: there
  // is no other to send it to.
  const actions = (
    <>
      <span aria-hidden className="h-3 w-px bg-border" />
      <Tooltip content={editing ? "Back to the rendered memory" : "Edit this memory"}>
        <button
          type="button"
          onClick={() => (editing ? guard(() => setEditing(false)) : setEditing(true))}
          className="inline-flex items-center gap-1 transition-colors hover:text-text"
        >
          {editing ? <Eye className="size-3.5" /> : <Pencil className="size-3.5" />}
          {editing ? "View" : "Edit"}
        </button>
      </Tooltip>
    </>
  );

  return (
    <div className="flex h-full flex-col overflow-hidden bg-paper">
      {editing && (
        <div className="flex h-8 flex-shrink-0 items-center gap-2 border-b border-border px-6 text-micro text-muted-foreground md:px-8">
          <span className="min-w-0 truncate font-mono text-text">{memory.key}</span>
          <div className="ml-auto flex flex-shrink-0 items-center gap-2">{actions}</div>
        </div>
      )}
      <div className="min-h-0 flex-1 overflow-y-auto">
        {editing ? (
          <MemoryEditor
            key={memory.key}
            memory={memory}
            roomName={roomName}
            actor={principal}
            onDirtyChange={setDirty}
            onSaved={() => {
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
              onNavigate={onOpenMemory}
              variant="page"
              renderedBody={renderedBody}
              collapseBodyAt={hasDiscussion ? BODY_CLAMP_PX : null}
              bodyFade="paper"
              showKey
              actions={actions}
            />
            {hasDiscussion && memory.episode && (
              <section className="border-t border-border px-6 py-3 md:px-8">
                <h2 className="mb-2 text-micro font-medium text-faint">Discussion</h2>
                <div className="max-w-prose [&_[data-testid=thread-conversation]_p]:px-0">
                  <TaskConversation
                    roomName={roomName}
                    episode={memory.episode}
                    onOpenMemory={onOpenMemory}
                    onReady={onThreadReady}
                  />
                  <RoomChatBox
                    roomName={roomName}
                    episode={memory.episode}
                    onSent={() => threadRefresh.current?.()}
                  />
                </div>
              </section>
            )}
          </>
        )}
      </div>
      {unsavedDialog}
    </div>
  );
}
