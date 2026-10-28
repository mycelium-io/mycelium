// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { useCurrentUser } from "@/components/current-user";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Kbd } from "@/components/ui/kbd";
import { Monogram } from "@/components/ui/monogram";
import { AgentCardHover } from "@/components/agent-card";
import { StartSwarmDialog } from "@/components/start-swarm-dialog";
import { shortAge } from "@/components/activity-rail";
import { NowProvider, useNow } from "@/lib/relative-time";
import { useRoomAgents, useRoomBoard, useRoomWaiting } from "@/lib/room-data";
import { useRoomStream } from "@/lib/stream-hub";
import { noticeOf, pingOf } from "@/lib/threads";
import type { BoardEpic, BoardPart, WaitingItem } from "@/lib/api";
import type { ParsedCapture } from "@/lib/board/capture";
import { fileCapture } from "@/lib/board/file-capture";
import {
  STANDING,
  WAITING_STANDING,
  epicLine,
  humanLine,
  sideBySide,
  isQuiet,
  lastMoved,
  progressOf,
  splitTasks,
  summary,
  titlesOf,
  waitingLine,
  waitingTitle,
  whoHasIt,
  type Standing,
} from "@/lib/board/people";
import { BoardCapture } from "./board-capture";

/** How long "Filed …" stands in for the board's summary line. */
const FILED_FOR_MS = 5000;

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
 * It reads like the app's rails, not a dashboard: a line that says what is
 * going on, a quiet line to hand something off, then the rows, edge to edge.
 * What is waiting on you comes first, then what is going on in the room (each
 * epic as a row with its parts indented under it, then the tasks someone is on
 * that stand alone), then what is up next. Every row is the same shape: who,
 * the title, one human line, its state as a dot and a word, and how long ago it
 * moved. A row opens its thread; j and k move between rows.
 *
 * The hub works all of it out (`GET /rooms/{room}/board` and `/waiting`). There
 * are no row actions: claiming, releasing and resolving are how agents move
 * work, from the CLI. A person hands work off and answers what they're asked.
 */
export function RoomBoard({ roomName, onOpenThread, onOpenMessage }: Props) {
  const { board, loading, refresh: refreshBoard } = useRoomBoard(roomName);
  const { principal } = useCurrentUser();
  const you = principal.replace(/^@/, "");
  const { items: waiting, refresh: refreshWaiting } = useRoomWaiting(roomName, you);
  const { agents } = useRoomAgents(roomName);
  const agentHandles = useMemo(() => new Set(agents.map(a => a.handle)), [agents]);
  const [swarmTask, setSwarmTask] = useState<string | null>(null);
  const [filing, setFiling] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);

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
          const filed = `Filed "${parsed.title}". An agent will pick it up.`;
          setFiling(filed);
          refreshBoard();
          // Said for a moment, then the line goes back to what's going on;
          // a refusal stays until the next thing is filed.
          setTimeout(() => setFiling(now => (now === filed ? null : now)), FILED_FOR_MS);
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

  // j and k move between rows, the way the rest of the app moves through a list;
  // Enter opens the row, since every row is a button.
  const move = useCallback((e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "j" && e.key !== "k") return;
    if ((e.target as HTMLElement).tagName === "INPUT") return;
    const rows = Array.from(listRef.current?.querySelectorAll<HTMLElement>("[data-board-row]") ?? []);
    if (rows.length === 0) return;
    e.preventDefault();
    const at = rows.indexOf(document.activeElement as HTMLElement);
    const next = e.key === "j" ? Math.min(rows.length - 1, at + 1) : Math.max(0, at - 1);
    rows[at === -1 ? 0 : next].focus();
  }, []);

  const titles = useMemo(() => titlesOf(board), [board]);
  // A task that's waiting on you lives there, not again below. An epic's part
  // stays in its epic, since the path would read wrong with a step missing.
  const yours = useMemo(() => new Set(waiting.map(item => item.key).filter(Boolean)), [waiting]);
  const { running, next } = splitTasks(board.tasks.filter(task => !yours.has(task.key)));
  const quietRoom = !loading && waiting.length === 0 && board.epics.length === 0 && board.tasks.length === 0;

  return (
    <div data-tour="board" className="@container flex h-full min-h-0 flex-col bg-bg">
      <div className="flex h-7 flex-shrink-0 items-center gap-3 border-b border-border bg-surface px-3 text-micro text-muted-foreground sm:px-4">
        <span className="min-w-0 truncate" role="status">
          {filing ?? (loading ? "" : summary(board.epics, [...running, ...next], waiting))}
        </span>
        <span className="ml-auto hidden flex-shrink-0 items-center gap-1 text-faint @[36rem]:flex">
          <Kbd size="xs" tone="muted">j</Kbd>
          <Kbd size="xs" tone="muted">k</Kbd>
          to move
          <Kbd size="xs" tone="muted">↵</Kbd>
          to open
        </span>
      </div>
      <BoardCapture
        actor={you || "you"}
        now={new Date().toISOString()}
        placeholder="Hand something off to the room…"
        onCapture={capture}
        onSwarm={text => setSwarmTask(text)}
      />

      <ScrollArea className="min-h-0 flex-1">
        <NowProvider>
          <div ref={listRef} onKeyDown={move} className="pb-4">
            {quietRoom && (
              <p className="px-3 py-3 text-label text-muted-foreground sm:px-4">
                Nothing is going on in this room yet. Hand something off above, and an agent will pick it up.
              </p>
            )}

            {waiting.length > 0 && (
              <Section label="Waiting on you" count={waiting.length}>
                {waiting.map(item => (
                  <WaitingRow
                    key={`${item.kind}:${item.episode ?? item.message_id ?? item.key}`}
                    item={item}
                    you={you}
                    agent={!!item.sender && agentHandles.has(item.sender)}
                    onOpen={() =>
                      item.episode ? open(item.episode) : item.message_id && onOpenMessage?.(item.message_id)
                    }
                  />
                ))}
              </Section>
            )}

            {(board.epics.length > 0 || running.length > 0) && (
              <Section label="In this room">
                {board.epics.map(epic => (
                  <EpicRows key={epic.key} epic={epic} you={you} titles={titles} agents={agentHandles} onOpen={open} />
                ))}
                {running.map(task => (
                  <TaskRow key={task.key} task={task} you={you} titles={titles} agents={agentHandles} onOpen={open} />
                ))}
              </Section>
            )}

            {next.length > 0 && (
              <Section label="Up next" count={next.length}>
                {next.map(task => (
                  <TaskRow key={task.key} task={task} you={you} titles={titles} agents={agentHandles} onOpen={open} />
                ))}
              </Section>
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

/** A section, labelled the way the rails label theirs, and folding to its label. */
function Section({ label, count, children }: { label: string; count?: number; children: ReactNode }) {
  const [folded, setFolded] = useState(false);
  return (
    <section aria-label={label} className="border-b border-border last:border-b-0">
      <button
        type="button"
        onClick={() => setFolded(f => !f)}
        aria-expanded={!folded}
        className="group flex h-7 w-full items-end gap-1.5 px-3 pb-1 text-micro font-medium text-faint sm:px-4"
      >
        {folded ? <ChevronRight className="size-3 self-center" /> : <ChevronDown className="size-3 self-center" />}
        <span className="group-hover:text-muted-foreground">{label}</span>
        {count !== undefined && <span className="font-normal tabular">{count}</span>}
      </button>
      {!folded && <ul className="flex flex-col pb-1">{children}</ul>}
    </section>
  );
}

function Dot({ tone }: { tone: string }) {
  return <span aria-hidden className="inline-block size-1.5 flex-shrink-0 rounded-full" style={{ background: tone }} />;
}

/**
 * The one row shape: who, the title, one human line, the state as a dot and a
 * word, and how long ago it moved. The columns line up down the whole board,
 * and a narrow pane keeps the title, the state's dot and the age.
 */
function Row({
  who,
  avatar,
  agent,
  title,
  line,
  standing,
  age,
  ageTitle,
  quiet,
  indent = 0,
  lead,
  rowKey,
  dim,
  onOpen,
}: {
  /** Who it's with, as the row says it ("you", a handle, or null for nobody). */
  who: string | null;
  /** The handle whose avatar the row wears, when `who` is "you". */
  avatar?: string;
  agent: boolean;
  title: string;
  line: string;
  standing: Standing;
  age: string;
  ageTitle?: string;
  quiet?: boolean;
  indent?: number;
  lead?: ReactNode;
  rowKey?: string;
  dim?: boolean;
  onOpen: () => void;
}) {
  return (
    <li>
      <button
        type="button"
        data-board-row={rowKey}
        onClick={onOpen}
        title={line ? `${title}\n${line}` : title}
        className="flex h-[26px] w-full items-center gap-2 px-3 text-left text-micro outline-none transition-colors hover:bg-hairline focus-visible:bg-hairline sm:px-4"
        style={indent ? { paddingLeft: `calc(${indent} * 1.25rem + 0.75rem)` } : undefined}
      >
        {lead ?? <span className="w-3 flex-shrink-0" />}
        <span className="flex w-4 flex-shrink-0 justify-center">
          {who ? (
            <AgentCardHover handle={avatar ?? who}>
              <span className="flex">
                <Monogram handle={avatar ?? who} className="size-4 text-[8px]" kind={agent ? "agent" : "person"} />
              </span>
            </AgentCardHover>
          ) : (
            <span aria-hidden className="size-3.5 rounded-full border border-dashed border-border2" />
          )}
        </span>
        <span className="grid min-w-0 flex-1 items-center gap-3 @[36rem]:grid-cols-[minmax(0,min(50%,26rem))_minmax(0,1fr)]">
          <span className={cn("min-w-0 truncate text-label", dim ? "text-muted-foreground" : "text-text")}>{title}</span>
          {line && <span className="hidden min-w-0 truncate text-faint @[36rem]:inline">{line}</span>}
        </span>
        {/* A blocked row's reason rides on its state too, since a narrow pane
            drops the line column and the reason is what you need there. */}
        <span
          className="flex flex-shrink-0 items-center gap-1.5 @[30rem]:w-[5.5rem]"
          style={{ color: standing.tone }}
          title={standing === STANDING.blocked && line ? line : undefined}
        >
          <Dot tone={standing.tone} />
          <span className="hidden truncate @[30rem]:inline">{standing.word}</span>
        </span>
        {/* Who has it opens their card. The row is a button, so focus is the
            row's: from the keyboard, the card is a hover away in Members. */}
        {who ? (
          <AgentCardHover handle={avatar ?? who}>
            <span className="hidden w-20 flex-shrink-0 truncate text-muted-foreground hover:text-text @[30rem]:inline">
              {who}
            </span>
          </AgentCardHover>
        ) : (
          <span className="hidden w-20 flex-shrink-0 truncate text-muted-foreground @[30rem]:inline">nobody yet</span>
        )}
        <span
          className={cn("tabular w-14 flex-shrink-0 text-right", quiet ? "text-yellow" : "text-faint")}
          title={ageTitle}
        >
          {age}
        </span>
      </button>
    </li>
  );
}

/** How long ago a task moved, and whether it has gone quiet. */
function useAge(part: BoardPart): { age: string; ageTitle?: string; quiet: boolean } {
  const now = useNow();
  const at = lastMoved(part);
  const quiet = isQuiet(part, now);
  const age = shortAge(at, now);
  return {
    age: quiet ? `quiet ${age}` : age,
    ageTitle: quiet ? `Nothing said in its thread for ${age}` : undefined,
    quiet,
  };
}

function WaitingRow({
  item,
  you,
  agent,
  onOpen,
}: {
  item: WaitingItem;
  you: string;
  agent: boolean;
  onOpen: () => void;
}) {
  const now = useNow();
  return (
    <Row
      // A task that's yours is with you; an ask or a turn is from whoever asked.
      who={item.kind === "task" ? "you" : (item.sender ?? null)}
      avatar={item.kind === "task" ? you : undefined}
      agent={item.kind !== "task" && agent}
      title={waitingTitle(item)}
      line={waitingLine(item, you)}
      standing={WAITING_STANDING[item.kind]}
      age={item.at ? shortAge(Date.parse(item.at), now) : ""}
      // Its own key: the task it's in may also have a row of its own below.
      rowKey={`waiting:${item.kind}:${item.key ?? item.message_id ?? ""}`}
      onOpen={onOpen}
    />
  );
}

function TaskRow({
  task,
  you,
  titles,
  agents,
  indent,
  lead,
  onOpen,
}: {
  task: BoardPart;
  you: string;
  titles: Map<string, string>;
  agents: Set<string>;
  indent?: number;
  lead?: ReactNode;
  onOpen: (episode?: string | null) => void;
}) {
  const who = whoHasIt(task, you);
  const { age, ageTitle, quiet } = useAge(task);
  return (
    <Row
      who={who}
      avatar={who === "you" ? you : undefined}
      agent={!!who && agents.has(who)}
      title={task.title}
      line={humanLine(task, titles)}
      standing={STANDING[task.state]}
      age={age}
      ageTitle={ageTitle}
      quiet={quiet}
      indent={indent}
      lead={lead}
      rowKey={task.key}
      dim={task.state === "done"}
      onOpen={() => onOpen(task.episode)}
    />
  );
}

/**
 * An epic as a tree: its own row, with how many of its parts are done, and its
 * parts indented under it in path order. A part's number is its step, so parts
 * that run side by side share one, the way `mycelium board show` numbers them.
 */
function EpicRows({
  epic,
  you,
  titles,
  agents,
  onOpen,
}: {
  epic: BoardEpic;
  you: string;
  titles: Map<string, string>;
  agents: Set<string>;
  onOpen: (episode?: string | null) => void;
}) {
  const [open, setOpen] = useState(true);
  const now = useNow();
  const parts = useMemo(() => new Map(epic.path.map(p => [p.key, p])), [epic.path]);
  const newest = Math.max(0, ...epic.path.map(lastMoved), lastMoved(epic));
  const quiet = epic.path.some(p => isQuiet(p, now)) && !epic.path.some(p => p.state === "working" && !isQuiet(p, now));
  const lead = epic.lead === you ? "you" : (epic.lead ?? null);
  const Chevron = open ? ChevronDown : ChevronRight;
  return (
    <>
      <Row
        who={lead}
        avatar={lead === "you" ? you : undefined}
        agent={!!lead && agents.has(lead)}
        title={epic.title}
        line={epicLine(epic, titles)}
        standing={{ word: progressOf(epic), tone: "var(--muted-foreground)" }}
        age={quiet ? `quiet ${shortAge(newest, now)}` : shortAge(newest, now)}
        quiet={quiet}
        rowKey={epic.key}
        lead={
          <span
            role="button"
            tabIndex={-1}
            aria-label={open ? `Hide the parts of ${epic.title}` : `Show the parts of ${epic.title}`}
            onClick={e => {
              e.stopPropagation();
              setOpen(o => !o);
            }}
            className="flex w-3 flex-shrink-0 justify-center text-faint hover:text-text"
          >
            <Chevron className="size-3" />
          </span>
        }
        onOpen={() => onOpen(epic.episode)}
      />
      {open &&
        epic.steps.flatMap((step, n) =>
          step.map(key => {
            const part = parts.get(key);
            if (!part) return null;
            return (
              <TaskRow
                key={key}
                task={part}
                you={you}
                titles={titles}
                agents={agents}
                indent={1}
                lead={
                  <span
                    className="w-3 flex-shrink-0 text-right font-mono text-faint"
                    title={sideBySide(key, step, titles)}
                  >
                    {n + 1}
                  </span>
                }
                onOpen={onOpen}
              />
            );
          }),
        )}
    </>
  );
}
