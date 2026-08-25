// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronLeft, Pencil, Eye } from "lucide-react";
import {
  fetchMemory,
  fetchMemoryExpanded,
  type Memory,
} from "@/lib/api";
import { useRoomMemoryIntegrity, useRoomRevalidate } from "@/lib/room-data";
import { memoryHref } from "@/lib/memory-routes";
import { isLiveEpisode } from "@/lib/threads";
import { MemoryDetail } from "@/components/memory-detail";
import { MemoryEditor } from "@/components/memory-editor";
import { RoomChatBox } from "@/components/room-chat-box";
import { TaskConversation } from "@/components/task/task-conversation";
import { Skeleton } from "@/components/ui/skeleton";
import { useCurrentUser } from "@/components/current-user";
import { useUnsavedGuard } from "@/components/unsaved-changes";

interface Props {
  roomName: string;
  memoryKey: string;
}

/** Full-page wiki view for one memory. */
export function MemoryPageView({ roomName, memoryKey }: Props) {
  const router = useRouter();
  const [memory, setMemory] = useState<Memory | null | undefined>(undefined);
  const [renderedBody, setRenderedBody] = useState<string | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const { integrity } = useRoomMemoryIntegrity(roomName);
  const { principal } = useCurrentUser();
  const revalidate = useRoomRevalidate(roomName);
  const { setDirty, guard, dialog: unsavedDialog } = useUnsavedGuard();

  useEffect(() => {
    let live = true;
    // Async fetch; the rest of the setState calls are in its .then(). Clearing
    // here keeps the previous memory from showing under the new key.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setMemory(undefined);
    setRenderedBody(null);
    fetchMemory(roomName, memoryKey).then(m => {
      if (!live) return;
      setMemory(m);
    });
    fetchMemoryExpanded(roomName, memoryKey).then(exp => {
      if (!live || !exp.found || !exp.rendered) return;
      setRenderedBody(exp.rendered);
    });
    return () => {
      live = false;
    };
  }, [roomName, memoryKey]);

  const onNavigate = useCallback(
    (key: string) => router.push(memoryHref(roomName, key)),
    [router, roomName],
  );

  // The thread conversation owns its own read; it hands us its refresh so the
  // page composer's send can re-read the episode.
  const threadRefresh = useRef<(() => void) | null>(null);
  const onThreadReady = useCallback((refresh: () => void) => {
    threadRefresh.current = refresh;
  }, []);

  if (memory === undefined) {
    return (
      <div className="mx-auto max-w-3xl px-6 py-10 space-y-4">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-5/6" />
      </div>
    );
  }

  if (memory === null) {
    return (
      <div className="mx-auto max-w-3xl px-6 py-10">
        <p className="text-body text-muted-foreground">Memory not found.</p>
        <Link
          href={`/room/${encodeURIComponent(roomName)}`}
          className="mt-4 inline-flex items-center gap-1 text-label text-accent"
        >
          <ChevronLeft className="size-4" />
          Back to room
        </Link>
      </div>
    );
  }

  const crumbs = memoryKey.split("/");

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <header className="sticky top-0 z-10 border-b border-border bg-surface/90 px-6 py-3 backdrop-blur-sm md:px-8">
        <Link
          href={`/room/${encodeURIComponent(roomName)}`}
          className="mb-2 inline-flex items-center gap-1 text-micro text-muted-foreground transition-colors hover:text-accent"
        >
          <ChevronLeft className="size-3.5" />
          {roomName}
        </Link>
        <div className="flex items-center gap-3">
          <h1 className="flex-1 font-mono text-ui font-semibold text-text break-all">
            {crumbs.map((part, i) => (
              <span key={i}>
                {i > 0 && <span className="text-faint">/</span>}
                {part}
              </span>
            ))}
          </h1>
          <button
            type="button"
            onClick={() =>
              isEditing ? guard(() => setIsEditing(false)) : setIsEditing(true)
            }
            className="inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-micro font-medium text-accent transition-colors hover:bg-hairline"
          >
            {isEditing ? <Eye className="size-3.5" /> : <Pencil className="size-3.5" />}
            {isEditing ? "View" : "Edit"}
          </button>
        </div>
      </header>

      <div className="mx-auto w-full max-w-3xl pb-12">
        {isEditing ? (
          <MemoryEditor
            key={memory.key}
            memory={memory}
            roomName={roomName}
            actor={principal}
            onDirtyChange={setDirty}
            onSaved={() => {
              // revalidate() refreshes every SWR-backed room resource, which
              // covers integrity. The memory and its expanded body are local
              // state, so refetch those directly.
              revalidate();
              setIsEditing(false);
              fetchMemory(roomName, memoryKey).then(m => { if (m) setMemory(m); });
              setRenderedBody(null);
              fetchMemoryExpanded(roomName, memoryKey).then(exp => {
                if (exp.found && exp.rendered) setRenderedBody(exp.rendered);
              });
            }}
            onCancel={() => guard(() => setIsEditing(false))}
          />
        ) : (
          <MemoryDetail
            memory={memory}
            roomName={roomName}
            onNavigate={onNavigate}
            variant="page"
            renderedBody={renderedBody}
            integrity={integrity}
          />
        )}

        {/* The task's discussion, below its body — the full-page equivalent of
            the thread pane's conversation. Only a real thread has one: a row
            written before threading carries the room's own live episode (or
            none), and reading that as a thread would empty the room's history. */}
        {!isEditing && memory.episode && !isLiveEpisode(roomName, memory.episode) && (
          <section className="mt-8 flex min-h-0 flex-col px-6 md:px-8">
            <h2 className="mb-2 text-micro uppercase tracking-wide text-faint">Discussion</h2>
            <div className="flex min-h-[16rem] flex-col rounded-xl border border-border bg-surface">
              <TaskConversation
                roomName={roomName}
                episode={memory.episode}
                onOpenMemory={onNavigate}
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
      </div>

      {unsavedDialog}
    </div>
  );
}
