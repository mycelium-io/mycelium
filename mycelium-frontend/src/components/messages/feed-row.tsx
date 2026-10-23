// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useMemo, useState } from "react";
import { AtSign, Braces, Copy, Link2, MessageSquare, Reply, TextQuote } from "lucide-react";
import type { VerifierFlag } from "@/lib/api";
import type { Event } from "@/lib/room-events";
import {
  useRoomAgents,
  useRoomRowNames,
  useRoomThreads,
  useRoomVerifierFlags,
  type RowNaming,
  type ThreadOwner,
} from "@/lib/room-data";
import { NOTICE_TYPE, PING_TYPE, noticeLabel, threadShortId } from "@/lib/threads";
import { claimNeedles } from "@/lib/verifier";
import { agentTag } from "@/lib/agent-label";
import { absoluteUrl, copyText } from "@/lib/clipboard";
import { insertIntoComposer, messagePath, quoteText, replyText } from "@/lib/message-actions";
import { Ago } from "@/lib/relative-time";
import {
  AGREED_ICON,
  DONE_ICON,
  JOIN_ICON,
  MEMORY_ICON,
  noticeIcon,
  THREAD_ICON,
  TIMEOUT_ICON,
  type EventIcon,
} from "@/lib/event-icons";
import { MessageBody } from "@/components/message-body";
import { MessageActions } from "@/components/message-actions";
import { RawMessageDialog } from "@/components/raw-message-dialog";
import { SenderName } from "@/components/sender-name";
import { VerifierLines } from "@/components/verifier-line";
import { ConductorRow } from "@/components/task/conductor-row";
import { EpisodeTag } from "@/components/episode-tag";
import { EventIconMark } from "@/components/event-icon";
import { Monogram } from "@/components/ui/monogram";
import { Tooltip } from "@/components/ui/tooltip";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";

/**
 * One row of a message list, drawn the same in every list that shows one: the
 * room's channel, a task's thread, a memory's discussion and an opened line in
 * the Stream. A chat message is a sender, its prose, its verifier lines, its
 * hover actions and its right-click menu; a conductor post is its structured
 * line; a lifecycle event is a quiet notice. What differs between lists is
 * which events they pass in, never how one is drawn.
 */

// The "raise-up" whitelist: message types promoted from the message inspector
// into the primary channel/chat surface. This must mirror
// contracts/channel-surface.json's `raise_up_types` byte-for-byte — the CLI
// (mycelium-cli/src/mycelium/commands/room.py) carries an independent copy,
// and event-stream.contract.test.ts asserts both stay in sync with the
// contract so the two surfaces can't silently drift apart.
export const RAISE_UP_TYPES = [
  "coordination_join",
  "coordination_consensus",
  "l9_knowledge",
];

/**
 * Lifecycle events that render as slim system notices (not chat rows). A chat
 * message only groups under the sender above it when no notice interrupts the
 * run. A ping is a system notice too, but is not on the shared raise-up list:
 * it is an `l9_exchange` already on the chat path, renamed by `parseEvent`.
 */
export const SYSTEM_TYPES = new Set([...RAISE_UP_TYPES, PING_TYPE, NOTICE_TYPE]);

/** Whether `ev` continues the run of messages `prev` started: same sender, and
 *  neither a notice nor a conductor line between them. */
export function groupsWith(prev: Event | undefined, ev: Event): boolean {
  return Boolean(prev && !SYSTEM_TYPES.has(prev.type) && !prev.conductor && prev.sender === ev.sender);
}

/** Who wrote the last row, when it is a message a row under it would group with. */
export function lastChatSender(rows: readonly Event[]): string | null {
  const last = rows[rows.length - 1];
  return last && !SYSTEM_TYPES.has(last.type) && !last.conductor ? last.sender : null;
}

/**
 * What to call a subject, and the thread that opens it.
 *
 * Read off the room's own rows, so a task reads in the feed as the name it
 * carries on the board rather than as its `work/…` slug. A notice carries its
 * own copy of both, which is what answers for a subject the room's memories do
 * not have — one filed a moment ago, or one since removed.
 */
export function nameActivity(
  subject: string,
  members: Event[],
  threads: Map<string, ThreadOwner>,
  rows: Map<string, RowNaming>,
): { title: string; episode: string | null } {
  const noticed = members.find((m) => m.type === NOTICE_TYPE)?.content;
  if (subject.startsWith("urn:")) {
    const owner = threads.get(subject);
    return {
      title: owner?.title ?? noticed ?? threadShortId(subject) ?? "thread",
      episode: subject,
    };
  }
  const row = rows.get(subject);
  return {
    title: row?.title ?? noticed ?? subject,
    episode: row?.episode ?? members.find((m) => m.thread)?.thread ?? null,
  };
}

/** What every row needs to know about the room it is drawn in. */
export interface FeedContext {
  roomName: string;
  agentHandles: Set<string>;
  engineHandles: Set<string>;
  /** What each agent is, said beside its name (`agentTag`). */
  agentTags: Map<string, string>;
  agentOwners: Map<string, string>;
  threads: Map<string, ThreadOwner>;
  rowNames: Map<string, RowNaming>;
  flagsByMessage: Map<string, VerifierFlag[]>;
  refreshFlags: () => void;
  onOpenThread?: (episode: string) => void;
  onOpenMemory?: (key: string) => void;
}

/** The room's shared reads, folded once for a list's rows. Each is a shared SWR
 *  entry, so a list asking costs no request of its own. */
export function useFeedContext(
  roomName: string,
  { onOpenThread, onOpenMemory }: Pick<FeedContext, "onOpenThread" | "onOpenMemory"> = {},
): FeedContext {
  const { agents } = useRoomAgents(roomName);
  const threads = useRoomThreads(roomName);
  const rowNames = useRoomRowNames(roomName);
  const { byMessage: flagsByMessage, refresh: refreshFlags } = useRoomVerifierFlags(roomName);
  return useMemo(
    () => ({
      roomName,
      agentHandles: new Set(agents.map((a) => a.handle)),
      engineHandles: new Set(agents.filter((a) => a.adapter === "engine").map((a) => a.handle)),
      agentTags: new Map(agents.map((a) => [a.handle, agentTag(a)])),
      agentOwners: new Map(agents.filter((a) => a.owner).map((a) => [a.handle, a.owner as string])),
      threads,
      rowNames,
      flagsByMessage,
      refreshFlags,
      onOpenThread,
      onOpenMemory,
    }),
    [roomName, agents, threads, rowNames, flagsByMessage, refreshFlags, onOpenThread, onOpenMemory],
  );
}

/** A quiet, centered lifecycle line woven into the conversation. */
export function SystemNotice({
  time,
  at,
  icon,
  label,
  labelColor,
  strong,
  task,
  children,
}: {
  time: string;
  /** When it landed, as an ISO stamp: shown as "2m ago", the exact time on hover. */
  at?: string;
  /** What kind of line it is, as an icon in its color (`lib/event-icons.ts`). */
  icon: EventIcon;
  label?: string;
  labelColor?: string;
  strong?: boolean;
  /** The task or thread it is about, in a column of one width, so every line's
   *  task starts and its detail starts at the same place down a run. A line
   *  about no task (`null` or left out) draws no column, not an empty one. */
  task?: React.ReactNode;
  /** The detail: who it was by or for, or the first line of what was said. */
  children?: React.ReactNode;
}) {
  // A run of notices reads as one block: space above the first, none between
  // them, so six tasks filed in a row take six lines rather than a screen. What
  // happened (or who said it), the task, the detail and when each keep a
  // column of their own.
  return (
    <div
      data-system-notice=""
      className="group mt-3 flex items-center gap-2 px-5 py-0.5 text-micro text-muted-foreground first:mt-0 [[data-system-notice]+&]:mt-0"
    >
      <EventIconMark icon={icon} />
      {label && (
        <span
          title={label}
          className={`w-1/5 max-w-32 flex-shrink-0 truncate whitespace-nowrap ${strong ? "font-semibold" : "font-medium"}`}
          style={{ color: labelColor ?? "var(--muted-foreground)" }}
        >
          {label}
        </span>
      )}
      {/* Shares of the row's width, up to a cap: every row is as wide as the
          next, so the columns still line up, and a narrow pane (a split
          beside a thread) leaves the detail room rather than squeezing it out. */}
      {task != null && <span className="flex w-1/3 min-w-0 max-w-64 flex-shrink-0 items-center">{task}</span>}
      {/* Up to a width, so on a wide window the detail stays near the task
          rather than drifting to the far edge. */}
      <span className="flex min-w-0 max-w-[36rem] flex-1 items-center gap-1.5 truncate">{children}</span>
      {/* Every line says when, even when the line above says the same: a
          blank here read as a line with no time. */}
      <span className="ml-auto flex w-16 flex-shrink-0 justify-end">
        {at ? (
          <Ago at={at} className="whitespace-nowrap tabular text-faint" />
        ) : (
          <span className="tabular text-faint">{time.slice(0, 5)}</span>
        )}
      </span>
    </div>
  );
}

/**
 * A message's right-click menu: copy what it says, or a link that opens the
 * room scrolled to it (the same `focus` link search results use), or see the
 * message exactly as the hub sent it. Selected text inside it keeps the
 * browser's own menu.
 */
export function MessageMenu({
  roomName,
  messageId,
  content,
  sender,
  wire,
  children,
}: {
  roomName: string;
  messageId?: string | null;
  content: string;
  sender: string;
  wire?: Record<string, unknown>;
  children: React.ReactElement;
}) {
  const [rawOpen, setRawOpen] = useState(false);
  return (
    <>
      {/* Mounted only while open, so a long list doesn't carry one per message. */}
      {rawOpen && wire && <RawMessageDialog open onClose={() => setRawOpen(false)} message={wire} />}
      <ContextMenu>
        <ContextMenuTrigger>{children}</ContextMenuTrigger>
        <ContextMenuContent>
          <ContextMenuItem
            icon={Reply}
            action="message.reply"
            onClick={() => insertIntoComposer({ room: roomName, text: replyText(sender) })}
          >
            Reply
          </ContextMenuItem>
          <ContextMenuItem
            icon={TextQuote}
            action="message.quote"
            onClick={() => insertIntoComposer({ room: roomName, text: quoteText(content, sender) })}
          >
            Quote
          </ContextMenuItem>
          <ContextMenuSeparator />
          <ContextMenuItem icon={Copy} action="message.copy" onClick={() => void copyText(content)}>
            Copy text
          </ContextMenuItem>
          {messageId && (
            <ContextMenuItem icon={Link2} onClick={() => void copyText(absoluteUrl(messagePath(roomName, messageId)))}>
              Copy link to message
            </ContextMenuItem>
          )}
          <ContextMenuItem icon={AtSign} onClick={() => void copyText(`@${sender}`)}>
            Copy @{sender}
          </ContextMenuItem>
          {wire && (
            <ContextMenuItem icon={Braces} onClick={() => setRawOpen(true)}>
              View raw message
            </ContextMenuItem>
          )}
        </ContextMenuContent>
      </ContextMenu>
    </>
  );
}

/** A run of a thread's pings, drawn as one line quoting its newest loaded message. */
export interface PingLine {
  said: Event;
  quote: string;
  count: number;
}

interface FeedRowProps {
  ev: Event;
  /** The row drawn above this one, for grouping and for a notice's age. */
  prev?: Event;
  ctx: FeedContext;
  /** A ping's quoted line; a ping without one draws nothing. */
  pingLine?: PingLine;
  /** Marked as the message arrived at (from search, or a link). */
  marked?: boolean;
  rowRef?: React.Ref<HTMLDivElement>;
  /** This row's share of an open find: words to mark, and whether it is the hit stood on. */
  hit?: { query: string[]; active: boolean };
  /** A conductor turn put to several members at once (`turnRuns`): everyone it
   *  went to, on the run's first turn, and `null` on the turns it folds in. */
  turnMembers?: string[] | null;
}

/** One event as a row: a notice, a conductor line or a chat message. */
export function FeedRow({ ev, prev, ctx, pingLine, marked = false, rowRef, hit, turnMembers }: FeedRowProps) {
  const { threads, rowNames, onOpenThread, onOpenMemory } = ctx;

  if (ev.type === PING_TYPE) {
    if (!pingLine || !ev.thread) return null;
    const { said, quote, count: n } = pingLine;
    const thread = ev.thread;
    const shortId = threadShortId(thread) ?? "thread";
    const owner = threads.get(thread);
    // One line from the thread: who, the task, and the first line of what they
    // said. The argument stays in the thread.
    return (
      <SystemNotice
        time={ev.time}
        at={ev.at}
        icon={THREAD_ICON}
        label={`@${said.sender || ev.pingSenders[0] || "someone"}`}
        labelColor="var(--text)"
        task={
          <button
            type="button"
            onClick={() => onOpenThread?.(thread)}
            disabled={!onOpenThread}
            title={owner?.title ?? thread}
            aria-label={`Open thread ${shortId}`}
            className="inline-flex max-w-full items-center gap-1 truncate rounded px-1 text-accent transition-colors enabled:hover:bg-accent-soft enabled:hover:underline disabled:cursor-default"
          >
            <MessageSquare className="size-3 shrink-0" strokeWidth={1.9} />
            <span className="truncate">{owner?.title ?? shortId}</span>
          </button>
        }
      >
        <span className="truncate text-text">{quote}</span>
        {n > 1 && <span className="flex-shrink-0 text-faint">· {n} messages</span>}
      </SystemNotice>
    );
  }

  if (ev.type === NOTICE_TYPE) {
    const episode = ev.thread;
    const by = ev.raw.by as string | undefined;
    const subkind = (ev.raw.subkind as string) || "filed";
    const change = ev.raw.change as string | undefined;
    // The icon says what happened and its color how it went; the table is
    // shared with the Stream tab (`lib/event-icons.ts`).
    const icon = noticeIcon(subkind, change, ev.raw.kind as string | undefined);
    const ref = ev.raw.ref as string | undefined;
    const prUrl = ev.raw.url as string | undefined;
    // A filed task reads by who it is for; anything else "by" who did it (a
    // lease event by who moved it); an expired one by who let it drain. Fall
    // back to the filer when a task is for no one.
    const detail =
      subkind === "upstream" ? (
        ref && prUrl ? (
          <a href={prUrl} target="_blank" rel="noreferrer" className="truncate hover:text-text hover:underline">
            {ref}
          </a>
        ) : (
          (ref ?? null)
        )
      ) : subkind === "filed" && ev.raw.for ? (
        `for @${String(ev.raw.for).replace(/^@/, "")}`
      ) : by ? (
        `${subkind === "expired" ? "held by" : "by"} @${by}`
      ) : null;
    return (
      <SystemNotice
        time={ev.time}
        at={ev.at}
        icon={icon}
        label={noticeLabel(subkind, ev.raw.kind as string | undefined, change)}
        task={
          <button
            type="button"
            onClick={() => episode && onOpenThread?.(episode)}
            disabled={!episode || !onOpenThread}
            title={ev.content}
            className="inline-flex max-w-full items-center gap-1 truncate rounded px-1 text-accent transition-colors enabled:hover:bg-accent-soft enabled:hover:underline disabled:cursor-default disabled:text-text"
          >
            <MessageSquare className="size-3 shrink-0" strokeWidth={1.9} />
            <span className="truncate">{ev.content}</span>
          </button>
        }
      >
        {typeof detail === "string" ? <span className="truncate">{detail}</span> : detail}
      </SystemNotice>
    );
  }

  if (ev.type === "l9_knowledge") {
    const key = ev.raw.key as string | undefined;
    const updatedBy = ev.raw.updated_by as string | undefined;
    const version = ev.raw.version;
    // The key printed once, as the name the room calls it — the content line
    // already said it, in slug form.
    const named = key ? nameActivity(key, [ev], threads, rowNames) : null;
    return (
      <SystemNotice
        time={ev.time}
        at={ev.at}
        icon={MEMORY_ICON}
        label="Knowledge"
        task={
          named ? (
            <button
              type="button"
              onClick={() => named.episode && onOpenThread?.(named.episode)}
              disabled={!named.episode || !onOpenThread}
              title={key}
              className="inline-flex max-w-full items-center gap-1 truncate rounded px-1 text-accent transition-colors enabled:hover:bg-accent-soft enabled:hover:underline disabled:cursor-default disabled:text-text"
            >
              <span className="truncate">{named.title}</span>
            </button>
          ) : (
            <span className="truncate px-1">{ev.content}</span>
          )
        }
      >
        <span className="truncate">
          updated{typeof version === "number" ? ` to v${version}` : ""}
          {updatedBy ? ` by @${updatedBy}` : ""}
        </span>
      </SystemNotice>
    );
  }

  if (ev.type === "coordination_consensus") {
    const broken = ev.raw.broken === true;
    const episodeUrn = (ev.raw.episode as string | undefined) ?? (ev.raw.session as string | undefined);
    const shortId = episodeUrn ? episodeUrn.split(":").pop() : undefined;
    const planFile = ev.raw.plan_file as string | undefined;
    const assignments = ev.raw.assignments as Record<string, string> | undefined;
    const issueCount = assignments ? Object.keys(assignments).length : 0;
    const metrics =
      ev.raw.metrics && typeof ev.raw.metrics === "object" ? (ev.raw.metrics as Record<string, unknown>) : undefined;
    const garRaw = metrics ? metrics.gar : undefined;
    const gar = typeof garRaw === "number" && Number.isFinite(garRaw) ? garRaw : undefined;
    const tone = broken ? "var(--yellow)" : "var(--green)";
    const openEpisode = onOpenThread && episodeUrn ? () => onOpenThread(episodeUrn) : undefined;
    // Named by its task, the way the channel's other lines are; a thread no
    // row carries falls back to its id.
    const title = episodeUrn ? threads.get(episodeUrn)?.title : undefined;
    const where = title ? (
      <button
        type="button"
        onClick={openEpisode}
        disabled={!openEpisode}
        title={title}
        aria-label={`Open thread ${shortId ?? title}`}
        className="inline-flex max-w-full items-center gap-1 truncate rounded px-1 text-accent transition-colors enabled:hover:bg-accent-soft enabled:hover:underline disabled:cursor-default disabled:text-text"
      >
        <MessageSquare className="size-3 shrink-0" strokeWidth={1.9} />
        <span className="truncate">{title}</span>
      </button>
    ) : shortId ? (
      <EpisodeTag urn={episodeUrn} shortId={shortId} onOpen={openEpisode} />
    ) : (
      <span className="px-1 font-mono">episode</span>
    );
    // A conductor run ends `resolved`, or `converged` when a pick certified an
    // agreement: a flow walked to its end, so it says which flow and how far
    // (and what it agreed on).
    const flowDone = ev.raw.outcome === "resolved" || ev.raw.outcome === "converged";
    const flow = flowDone ? (ev.raw.protocol as string | undefined) : undefined;
    if (flow) {
      const steps = typeof ev.raw.steps === "number" ? ev.raw.steps : undefined;
      const agreed =
        ev.raw.outcome === "converged" ? ((ev.raw.select as { pick?: string } | undefined)?.pick ?? null) : null;
      return (
        <SystemNotice
          time={ev.time}
          at={ev.at}
          icon={agreed ? AGREED_ICON : DONE_ICON}
          label={agreed ? "Agreed" : "Done"}
          labelColor={tone}
          strong
          task={where}
        >
          <span className="truncate">
            {flow} flow
            {steps !== undefined ? `, ${steps} step${steps === 1 ? "" : "s"}` : ""}
            {agreed ? `, going with ${agreed}` : ""}
          </span>
        </SystemNotice>
      );
    }
    return (
      <SystemNotice
        time={ev.time}
        at={ev.at}
        icon={broken ? TIMEOUT_ICON : AGREED_ICON}
        label={broken ? "Timeout" : "Consensus"}
        labelColor={tone}
        strong
        task={where}
      >
        {broken ? (
          <span>no agreement</span>
        ) : (
          <>
            <span>
              {issueCount} issue{issueCount === 1 ? "" : "s"} agreed
            </span>
            {gar !== undefined ? (
              <Tooltip content="Genuine agreement ratio: how many agents actually moved toward the outcome">
                <span
                  className="font-mono"
                  aria-description="Genuine agreement ratio: how many agents actually moved toward the outcome"
                >
                  · GAR {gar.toFixed(2)}
                </span>
              </Tooltip>
            ) : null}
            {planFile ? (
              <span>
                → <span className="font-mono text-accent">{planFile}</span>
              </span>
            ) : null}
          </>
        )}
      </SystemNotice>
    );
  }

  if (ev.type === "coordination_join") {
    const handle = (ev.raw.handle as string | undefined) ?? ev.sender;
    const intent = (ev.raw.intent as string | undefined) ?? "";
    const episodeUrn = (ev.raw.episode as string | undefined) ?? (ev.raw.session as string | undefined);
    const shortId = episodeUrn ? episodeUrn.split(":").pop() : undefined;
    return (
      <SystemNotice
        time={ev.time}
        at={ev.at}
        icon={JOIN_ICON}
        label={`@${handle}`}
        task={
          shortId ? (
            <EpisodeTag
              urn={episodeUrn}
              shortId={shortId}
              onOpen={onOpenThread && episodeUrn ? () => onOpenThread(episodeUrn) : undefined}
            />
          ) : null
        }
      >
        <span className="truncate">
          joined{intent ? <>: &ldquo;{intent}&rdquo;</> : null}
        </span>
      </SystemNotice>
    );
  }

  // A conductor post is drawn from its structured line: one row naming the
  // step and who it went to, the prompt behind a toggle.
  if (ev.conductor) {
    // A turn folded into the row of the run it belongs to keeps its anchor
    // and draws nothing.
    if (turnMembers === null) return <div data-event-id={ev.id} />;
    return (
      <div data-event-id={ev.id}>
        <ConductorRow line={ev.conductor} text={ev.content} onOpenMemory={onOpenMemory} members={turnMembers} />
      </div>
    );
  }

  return <MessageRow ev={ev} grouped={groupsWith(prev, ev)} ctx={ctx} marked={marked} rowRef={rowRef} hit={hit} />;
}

/** A chat message: who said it (once per run), what they said, the verifier's
 *  lines under it, its hover actions and its right-click menu. */
export function MessageRow({
  ev,
  grouped,
  ctx,
  marked = false,
  rowRef,
  hit,
}: {
  ev: Event;
  grouped: boolean;
  ctx: FeedContext;
  marked?: boolean;
  rowRef?: React.Ref<HTMLDivElement>;
  hit?: { query: string[]; active: boolean };
}) {
  const { roomName, agentHandles, engineHandles, agentTags, agentOwners, flagsByMessage, refreshFlags } = ctx;
  const isAgent = agentHandles.has(ev.sender);
  // Match the members panel so one sender isn't two colors in two places: an
  // agent wears its own stable tint (Monogram's default), a human the neutral seat.
  const color = isAgent ? undefined : "var(--avatar-neutral)";
  const owner = isAgent ? agentOwners.get(ev.sender) : undefined;
  const flags = ev.messageId ? flagsByMessage.get(ev.messageId) : undefined;
  return (
    <MessageMenu roomName={roomName} messageId={ev.messageId} content={ev.content} sender={ev.sender} wire={ev.wire}>
      <div
        data-event-id={ev.id}
        ref={rowRef}
        className={`group relative flex gap-3 px-5 hover:bg-hairline ${grouped ? "py-0.5" : "mt-3 pt-1 first:mt-0"} ${
          marked ? "bg-accent/15" : ""
        } ${hit?.active ? "bg-yellow/10 ring-1 ring-inset ring-yellow/40" : ""}`}
      >
        <div className="w-6 flex-shrink-0">
          {!grouped && (
            <Tooltip content={owner ? `@${ev.sender} · owned by @${owner}` : ev.sender}>
              <span role="img" aria-label={owner ? `@${ev.sender} · owned by @${owner}` : ev.sender}>
                <Monogram
                  handle={ev.sender}
                  color={color}
                  className="size-6 text-[10px]"
                  kind={engineHandles.has(ev.sender) ? "engine" : isAgent ? "agent" : "person"}
                />
              </span>
            </Tooltip>
          )}
        </div>
        <div className="min-w-0 flex-1">
          {!grouped && (
            <div className="flex items-center gap-1.5 pr-12">
              <SenderName
                handle={ev.sender}
                highlight={hit}
                tag={isAgent ? (agentTags.get(ev.sender) ?? "agent") : undefined}
              />
              {ev.recipient && (
                <span className="flex-shrink-0 rounded bg-hairline px-1.5 py-0.5 text-[11px] leading-none text-muted-foreground">
                  → {ev.recipient}
                </span>
              )}
              <Ago at={ev.at} className="flex-shrink-0 whitespace-nowrap text-micro tabular text-faint" />
            </div>
          )}
          <MessageBody
            content={ev.content}
            hit={hit}
            claims={flags ? claimNeedles(ev.content, flags.flatMap((f) => f.quotes)) : undefined}
            onOpenMemory={ctx.onOpenMemory}
            roomName={roomName}
          />
          {ev.edited && (
            <span className="text-micro text-faint" title="revised by a later message">
              (edited)
            </span>
          )}
          {flags && <VerifierLines roomName={roomName} flags={flags} onChanged={refreshFlags} />}
        </div>
        <MessageActions
          roomName={roomName}
          messageId={ev.messageId}
          content={ev.content}
          sender={ev.sender}
          wire={ev.wire}
          onOpenThread={ctx.onOpenThread}
          // A follow-up line shows its clock time on hover, in the bar; the
          // group's header already says how long ago.
          time={grouped ? ev.time.slice(0, 5) : undefined}
        />
      </div>
    </MessageMenu>
  );
}
