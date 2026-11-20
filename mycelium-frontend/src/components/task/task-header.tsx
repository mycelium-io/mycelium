// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useMemo, useState } from "react";
import { Check, Hand, Loader2, Undo2 } from "lucide-react";

import { writeAssignment, type BoardEpic, type BoardPart, type Memory, type PartState } from "@/lib/api";
import { STANDING } from "@/lib/board/people";
import { memoryTitle } from "@/lib/memory-preview";
import { useRoomBoard, useRoomRevalidate, useRoomRoster } from "@/lib/room-data";
import { useCurrentUser } from "@/components/current-user";
import { AgentCardHover } from "@/components/agent-card";
import { Button } from "@/components/ui/button";
import { Monogram } from "@/components/ui/monogram";
import { cn } from "@/lib/utils";

const bare = (handle: unknown) => (typeof handle === "string" ? handle.replace(/^@/, "") : "");

/** The board's row for a key, and the epic it's a part of, if any. */
function findRow(epics: BoardEpic[], tasks: BoardPart[], key: string): { row: BoardPart | null; epic: BoardEpic | null } {
  for (const epic of epics) {
    if (epic.key === key) return { row: epic, epic: null };
    const part = epic.path.find((p) => p.key === key);
    if (part) return { row: part, epic };
  }
  return { row: tasks.find((t) => t.key === key) ?? null, epic: null };
}

/**
 * The top of a task's page: its title as the page's heading, where it stands
 * and who holds it, and what a person can do with it from here. The board
 * works out the state; a task off the board is done when its row says resolved.
 */
export function TaskHeader({ roomName, memory, className }: { roomName: string; memory: Memory; className?: string }) {
  const { board } = useRoomBoard(roomName);
  const { agents } = useRoomRoster(roomName);
  const { principal } = useCurrentUser();
  const revalidate = useRoomRevalidate(roomName);
  const [busy, setBusy] = useState<"claim" | "release" | "resolve" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { row, epic } = useMemo(() => findRow(board.epics, board.tasks, memory.key), [board, memory.key]);
  const meta = memory.meta ?? {};
  const resolved = meta.assignment === "resolved" || meta.status === "resolved";
  const state: PartState = row?.state ?? (resolved ? "done" : "open");
  const standing = STANDING[state];
  const holder = bare(row?.holder) || (meta.assignment === "held" ? bare(meta.owner) : "");
  const me = bare(principal);
  const mine = !!me && holder === me;
  const agentHandles = useMemo(() => new Set(agents.map((a) => a.handle.toLowerCase())), [agents]);
  const progress = row && "total" in row ? (row as BoardEpic) : null;

  const act = async (action: "claim" | "release" | "resolve") => {
    if (!me) return;
    setBusy(action);
    setError(null);
    try {
      await writeAssignment(roomName, action, { key: memory.key, handle: me });
      revalidate();
    } catch (e) {
      setError(e instanceof Error ? e.message : "The hub didn't take it");
    } finally {
      setBusy(null);
    }
  };
  const spin = (action: typeof busy) => (busy === action ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : null);

  return (
    <div className={cn("pt-6 pb-4", className)}>
      {epic && <div className="mb-1.5 truncate text-micro text-faint">Part of {epic.title}</div>}
      <h1 className="text-[20px] leading-snug font-medium text-text">{row?.title ?? memoryTitle(memory)}</h1>
      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2">
        <span className="flex items-center gap-1.5 text-label" style={{ color: standing.tone }}>
          <span aria-hidden className="size-2 rounded-full" style={{ background: standing.tone }} />
          {standing.word}
        </span>
        {holder ? (
          <AgentCardHover handle={holder}>
            <span className="flex items-center gap-1.5 text-label text-muted-foreground">
              <Monogram
                handle={holder}
                kind={agentHandles.has(holder.toLowerCase()) ? "agent" : "person"}
                className="size-5 text-[9px]"
              />
              Held by {mine ? "you" : `@${holder}`}
            </span>
          </AgentCardHover>
        ) : (
          state !== "done" && <span className="text-label text-muted-foreground">Nobody holds it</span>
        )}
        {progress && progress.total > 0 && (
          <span className="text-label text-muted-foreground">
            {progress.done} of {progress.total} parts done
          </span>
        )}
        {state !== "done" && me && (
          <span className="ml-auto flex items-center gap-1.5">
            {mine ? (
              <Button variant="ghost" size="sm" disabled={!!busy} onClick={() => void act("release")}>
                {spin("release") ?? <Undo2 className="size-3.5" aria-hidden />}
                Release
              </Button>
            ) : (
              !holder && (
                <Button variant="ghost" size="sm" disabled={!!busy} onClick={() => void act("claim")}>
                  {spin("claim") ?? <Hand className="size-3.5" aria-hidden />}
                  Claim
                </Button>
              )
            )}
            <Button variant="secondary" size="sm" disabled={!!busy} onClick={() => void act("resolve")}>
              {spin("resolve") ?? <Check className="size-3.5" aria-hidden />}
              Resolve
            </Button>
          </span>
        )}
      </div>
      {error && (
        <p role="alert" className="mt-2 text-micro text-red">
          {error}
        </p>
      )}
    </div>
  );
}
