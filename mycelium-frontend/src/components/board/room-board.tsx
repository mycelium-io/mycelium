// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useMemo, useState } from "react";
import { Check, ChevronDown, ChevronRight, ListChecks } from "lucide-react";
import { cn } from "@/lib/utils";
import { useCurrentUser } from "@/components/current-user";
import { ScrollArea } from "@/components/ui/scroll-area";
import { EmptyState } from "@/components/empty-state";
import { Monogram } from "@/components/ui/monogram";
import { StartSwarmDialog } from "@/components/start-swarm-dialog";
import { NowProvider, useNow } from "@/lib/relative-time";
import { useRoomBoard, useRoomRoster, useRoomWaiting } from "@/lib/room-data";
import { useRoomStream } from "@/lib/stream-hub";
import { noticeOf, pingOf } from "@/lib/threads";
import type { BoardEpic, BoardPart, WaitingItem } from "@/lib/api";
import type { ParsedCapture } from "@/lib/board/capture";
import { fileCapture } from "@/lib/board/file-capture";
import {
  progressOf,
  quietFor,
  splitTasks,
  titlesOf,
  waitingText,
  whereItStands,
  whoHasIt,
} from "@/lib/board/people";
import { BoardCapture } from "./board-capture";

interface Props {
  roomName: string;
  /** Open a task's thread. The pane it opens belongs to the room's workspace. */
  onOpenThread?: (episode: string) => void;
  /** Open one message in the room, for an ask made outside any task. */
  onOpenMessage?: (id: string) => void;
}

/**
 * The board, for people.
 *
 * From the top: a line to hand something off, what is waiting on you, what is
 * going on in the room (each epic as a path of its parts, then the tasks
 * someone is on that stand alone), and what is up next. The hub works all of
 * it out (`GET /rooms/{room}/board` and `/waiting`); this draws it.
 *
 * There are no row actions here. Claiming, releasing and resolving are how
 * agents move work, and they do it from the CLI; a person hands work off and
 * answers what is asked of them.
 */
export function RoomBoard({ roomName, onOpenThread, onOpenMessage }: Props) {
  const { board, loading, refresh: refreshBoard } = useRoomBoard(roomName);
  const { principal } = useCurrentUser();
  const you = principal.replace(/^@/, "");
  const { items: waiting, refresh: refreshWaiting } = useRoomWaiting(roomName, you);
  const { agents } = useRoomRoster(roomName);
  const agentHandles = useMemo(() => new Set(agents.map(a => a.handle)), [agents]);
  const [swarmTask, setSwarmTask] = useState<string | null>(null);
  const [filing, setFiling] = useState<string | null>(null);

  // The board moves when a task is filed, taken or finished (a notice), when a
  // thread gets a new line (a ping), or when a row is rewritten.
  useRoomStream(roomName, frame => {
    const message = frame as Record<string, unknown>;
    if (message.message_type === "memory_changed") {
      refreshBoard();
      refreshWaiting();
      return;
    }
    let content = message.content;
    if (typeof content === "string") {
      try {
        content = JSON.parse(content);
      } catch {
        return;
      }
    }
    const raw = content as Record<string, unknown> | null;
    if (noticeOf(raw) || pingOf(raw)) {
      refreshBoard();
      refreshWaiting();
    }
  });

  const capture = useCallback(
    (parsed: ParsedCapture) => {
      setFiling(`Filing "${parsed.title}"…`);
      fileCapture(roomName, parsed, you || "you")
        .then(() => {
          setFiling(`Filed "${parsed.title}". An agent will pick it up.`);
          refreshBoard();
        })
        .catch(err => setFiling(`Couldn't file "${parsed.title}": ${err instanceof Error ? err.message : err}`));
    },
    [refreshBoard, roomName, you],
  );

  const open = useCallback(
    (episode?: string | null) => {
      if (episode) onOpenThread?.(episode);
    },
    [onOpenThread],
  );

  // What a waiting task waits on is named by its title wherever the board has one.
  const titles = useMemo(() => {
    const named = new Map<string, string>();
    for (const epic of board.epics) for (const [key, title] of titlesOf(epic)) named.set(key, title);
    for (const task of board.tasks) named.set(task.key, task.title);
    return named;
  }, [board]);
  const { running, next } = splitTasks(board.tasks);
  const inRoom = board.epics.length + running.length;
  const empty = !loading && waiting.length === 0 && inRoom === 0 && next.length === 0;

  return (
    <div data-tour="board" className="@container flex h-full min-h-0 flex-col bg-bg">
      <ScrollArea className="h-full">
        <NowProvider>
          <div className="mx-auto flex w-full max-w-5xl flex-col gap-7 px-4 py-5 sm:px-6">
            <div>
              <BoardCapture
                actor={you || "you"}
                now={new Date().toISOString()}
                placeholder="Tell the room what you need and an agent will pick it up…"
                onCapture={capture}
                onSwarm={text => setSwarmTask(text)}
              />
              {filing && <p className="mt-1.5 px-1 text-micro text-muted-foreground" role="status">{filing}</p>}
            </div>

            {empty ? (
              <EmptyState
                icon={ListChecks}
                title="Nothing is going on in this room yet"
                description="Tell the room what you need above, and an agent will pick it up."
              />
            ) : (
              <>
                {waiting.length > 0 && (
                  <Section title="Waiting on you" count={waiting.length}>
                    <ul className="divide-y divide-border overflow-hidden rounded-lg border border-border bg-paper">
                      {waiting.map(item => (
                        <WaitingRow
                          key={`${item.kind}:${item.episode ?? item.message_id ?? item.key}`}
                          item={item}
                          you={you}
                          agent={!!item.sender && agentHandles.has(item.sender)}
                          onAnswer={() =>
                            item.episode
                              ? open(item.episode)
                              : item.message_id && onOpenMessage?.(item.message_id)
                          }
                        />
                      ))}
                    </ul>
                  </Section>
                )}

                {inRoom > 0 && (
                  <Section title="In this room" count={inRoom}>
                    <div className="flex flex-col gap-3">
                      {board.epics.map(epic => (
                        <EpicPath key={epic.key} epic={epic} you={you} onOpen={open} />
                      ))}
                      {running.length > 0 && (
                        <ul className="divide-y divide-border overflow-hidden rounded-lg border border-border bg-paper">
                          {running.map(task => (
                            <RunningTask key={task.key} task={task} you={you} onOpen={open} />
                          ))}
                        </ul>
                      )}
                    </div>
                  </Section>
                )}

                {next.length > 0 && (
                  <Section title="Up next" count={next.length}>
                    <ul className="divide-y divide-border overflow-hidden rounded-lg border border-border bg-paper">
                      {next.map(task => (
                        <NextTask key={task.key} task={task} you={you} titles={titles} onOpen={open} />
                      ))}
                    </ul>
                  </Section>
                )}
              </>
            )}
          </div>
        </NowProvider>
      </ScrollArea>

      {/* Mounted only while open, so each opening starts from what was typed. */}
      {swarmTask !== null && (
        <StartSwarmDialog open onClose={() => setSwarmTask(null)} roomName={roomName} initialTask={swarmTask} />
      )}
    </div>
  );
}

function Section({ title, count, children }: { title: string; count: number; children: React.ReactNode }) {
  return (
    <section aria-label={title} className="flex flex-col gap-2.5">
      <h2 className="flex items-baseline gap-2 text-ui font-medium text-text">
        {title}
        <span className="text-label text-muted-foreground">{count}</span>
      </h2>
      {children}
    </section>
  );
}

function WaitingRow({
  item,
  you,
  agent,
  onAnswer,
}: {
  item: WaitingItem;
  you: string;
  agent: boolean;
  onAnswer: () => void;
}) {
  const text = waitingText(item, you);
  return (
    <li className="flex items-center gap-3 px-4 py-3">
      {item.sender ? (
        <Monogram handle={item.sender} className="size-6 shrink-0 text-[10px]" kind={agent ? "agent" : "person"} />
      ) : (
        <span aria-hidden className="grid size-6 shrink-0 place-items-center rounded-full border border-border">
          <span className="size-2 rounded-full bg-accent" />
        </span>
      )}
      <div className="min-w-0 flex-1">
        <p className="truncate text-label text-text" title={text}>
          {text}
        </p>
        {item.kind === "ask" && item.count > 1 && (
          <p className="text-micro text-muted-foreground">
            {item.sender} asked {item.count} times in this task.
          </p>
        )}
      </div>
      {item.epic_title && (
        <span className="hidden shrink-0 truncate text-micro text-muted-foreground @xl:block">
          Part of {item.epic_title}
        </span>
      )}
      <button
        type="button"
        onClick={onAnswer}
        className="shrink-0 rounded-md border border-border bg-bg px-3 py-1 text-label text-text transition-colors hover:bg-hairline"
      >
        Answer
      </button>
    </li>
  );
}

/** A part's mark on the path: done, someone on it, or nobody yet. */
function Mark({ part, yours }: { part: BoardPart; yours: boolean }) {
  if (part.state === "done") {
    return (
      <span className="grid size-6 place-items-center rounded-full bg-green text-bg">
        <Check className="size-3.5" strokeWidth={3} />
      </span>
    );
  }
  const ring =
    part.state === "blocked"
      ? "border-red"
      : part.state === "working"
        ? yours
          ? "border-accent"
          : "border-text"
        : "border-border";
  return (
    <span className={cn("grid size-6 place-items-center rounded-full border-2 bg-bg", ring)}>
      {part.state === "working" && <span className={cn("size-2 rounded-full", yours ? "bg-accent" : "bg-text")} />}
    </span>
  );
}

function EpicPath({ epic, you, onOpen }: { epic: BoardEpic; you: string; onOpen: (episode?: string | null) => void }) {
  const [open, setOpen] = useState(true);
  const now = useNow();
  const titles = useMemo(() => titlesOf(epic), [epic]);
  const parts = useMemo(() => new Map(epic.path.map(p => [p.key, p])), [epic.path]);
  const quiet = quietFor(epic.path, now);
  const Chevron = open ? ChevronDown : ChevronRight;
  return (
    <article className="overflow-hidden rounded-lg border border-border bg-paper">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border px-4 py-3">
        <button
          type="button"
          onClick={() => setOpen(o => !o)}
          aria-expanded={open}
          aria-label={open ? `Hide the parts of ${epic.title}` : `Show the parts of ${epic.title}`}
          className="-ml-1 rounded p-0.5 text-muted-foreground hover:bg-hairline hover:text-text"
        >
          <Chevron className="size-4" />
        </button>
        <button
          type="button"
          onClick={() => onOpen(epic.episode)}
          className="min-w-0 truncate text-left text-body font-medium text-text hover:underline"
        >
          {epic.title}
        </button>
        <span className="text-label text-muted-foreground">
          {progressOf(epic)}
          {epic.lead && <> · led by {epic.lead === you ? "you" : epic.lead}</>}
        </span>
        {quiet && <span className="ml-auto text-label text-yellow">{quiet}</span>}
      </header>
      {open && (
        <ol aria-label={`The parts of ${epic.title}, in order`} className="flex flex-col gap-4 px-4 py-4 @3xl:flex-row @3xl:gap-0">
          {epic.steps.map((step, n) => (
            <li key={step.join("+")} className="relative flex flex-1 flex-col gap-4 @3xl:min-w-0 @3xl:pr-4">
              {/* The path's line runs through each step's first mark. */}
              {n < epic.steps.length - 1 && (
                <span aria-hidden className="absolute left-3 top-3 hidden h-px w-full bg-border @3xl:block" />
              )}
              {step.length > 1 && (
                <span className="text-micro text-muted-foreground @3xl:order-last">These run side by side.</span>
              )}
              {step.map(key => {
                const part = parts.get(key);
                if (!part) return null;
                const who = whoHasIt(part, you);
                return (
                  <button
                    key={key}
                    type="button"
                    data-board-row={key}
                    onClick={() => onOpen(part.episode)}
                    className="relative z-10 flex gap-3 rounded-md text-left @3xl:flex-col @3xl:gap-2"
                  >
                    <span className="shrink-0 pt-0.5">
                      <Mark part={part} yours={who === "you"} />
                    </span>
                    <span className="flex min-w-0 flex-col gap-0.5">
                      <span className={cn("text-label font-medium", part.state === "open" || part.state === "waiting" ? "text-muted-foreground" : "text-text")}>
                        {part.title}
                      </span>
                      <span className="text-micro text-muted-foreground">{who}</span>
                      <span
                        className={cn("line-clamp-2 text-micro", who === "you" && part.state !== "done" ? "text-accent" : "text-muted-foreground")}
                        title={whereItStands(part, titles)}
                      >
                        {whereItStands(part, titles)}
                      </span>
                    </span>
                  </button>
                );
              })}
            </li>
          ))}
        </ol>
      )}
    </article>
  );
}

function RunningTask({ task, you, onOpen }: { task: BoardPart; you: string; onOpen: (episode?: string | null) => void }) {
  const now = useNow();
  const who = whoHasIt(task, you);
  const quiet = quietFor([task], now);
  return (
    <li>
      <button
        type="button"
        data-board-row={task.key}
        onClick={() => onOpen(task.episode)}
        className="flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-hairline"
      >
        <span className="shrink-0 pt-0.5">
          <Mark part={task} yours={who === "you"} />
        </span>
        <span className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className="text-label font-medium text-text">{task.title}</span>
          <span className="truncate text-micro text-muted-foreground">{whereItStands(task)}</span>
        </span>
        <span className="flex shrink-0 flex-col items-end gap-0.5 text-micro">
          <span className="text-muted-foreground">{who}</span>
          {quiet && <span className="text-yellow">{quiet}</span>}
        </span>
      </button>
    </li>
  );
}

function NextTask({
  task,
  you,
  titles,
  onOpen,
}: {
  task: BoardPart;
  you: string;
  titles: Map<string, string>;
  onOpen: (episode?: string | null) => void;
}) {
  const who = whoHasIt(task, you);
  return (
    <li>
      <button
        type="button"
        data-board-row={task.key}
        onClick={() => onOpen(task.episode)}
        className="flex w-full flex-wrap items-baseline gap-x-3 gap-y-0.5 px-4 py-3 text-left transition-colors hover:bg-hairline"
      >
        <span className="min-w-0 text-label text-text">{task.title}</span>
        {task.state === "waiting" && (
          <span className="text-micro text-muted-foreground">{whereItStands(task, titles)}</span>
        )}
        <span className="ml-auto text-micro text-muted-foreground">{who}</span>
      </button>
    </li>
  );
}
