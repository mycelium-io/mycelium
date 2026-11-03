// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * An agent's session drawn as what it did rather than as its screen: what it
 * was asked, what it said, its plan, and each tool it called with how that
 * went. It is the other side of the terminal window's toggle, and reads the
 * same session from the same machine (`lib/agent-session.ts`).
 *
 * A tool call is one line, and opens to its result, its change, and the call
 * as the CLI wrote it. Reads in a row fold into one line. A sub-agent's work
 * opens beneath its call. What only the terminal shows, such as a permission
 * prompt, is said at the bottom with the way back to the terminal, and when
 * the pane's state can't be read the bottom says nothing rather than guess.
 *
 * `SessionUnavailable` is what the rendered side shows when there's no
 * session to draw: no converter for the CLI, or no session file found.
 */

import { useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRightLeft,
  Bell,
  Bot,
  Brain,
  Braces,
  Check,
  ChevronRight,
  Circle,
  CircleCheck,
  CircleDot,
  FilePen,
  FileSearch,
  FileText,
  Globe,
  ListChecks,
  Loader2,
  MessageCircleQuestion,
  Search,
  SquareTerminal,
  Trash2,
  UserRound,
  Wrench,
  X,
} from "lucide-react";
import {
  diffLines,
  textOf,
  type AgentSession,
  type Plan,
  type SessionEntry,
  type ToolCall,
  type ToolKind,
  type Unavailable,
} from "@/lib/agent-session";
import { MarkdownContent } from "@/components/markdown-content";
import { cn } from "@/lib/utils";

const TOOL_ICON: Record<ToolKind, typeof Wrench> = {
  read: FileText,
  edit: FilePen,
  delete: Trash2,
  move: ArrowRightLeft,
  search: Search,
  execute: SquareTerminal,
  think: Brain,
  fetch: Globe,
  switch_mode: ArrowRightLeft,
  other: Wrench,
};

/** Where to read how an agent CLI's integration reads its sessions. */
export const ADD_SESSION_SUPPORT_URL =
  "https://github.com/mycelium-io/mycelium/tree/main/mycelium-cli/src/mycelium/integrations/agents";

/** How close to the bottom, in pixels, still counts as following along. */
const FOLLOW_SLACK_PX = 24;

/** Consecutive reads, folded into one line. */
type Row = SessionEntry | { sessionUpdate: "reads"; _meta: { id: string }; calls: ToolCall[] };

const isRead = (e: SessionEntry) => e.sessionUpdate === "tool_call" && e.kind === "read" && e.status !== "failed";

function rowsOf(entries: SessionEntry[]): Row[] {
  const rows: Row[] = [];
  // ACP sends a plan whole each time it changes: only the latest is drawn.
  const lastPlan = entries.findLastIndex((e) => e.sessionUpdate === "plan");
  entries.forEach((entry, i) => {
    if (entry.sessionUpdate === "plan" && i !== lastPlan) return;
    const last = rows.at(-1);
    if (isRead(entry) && last?.sessionUpdate === "reads") last.calls.push(entry as ToolCall);
    else if (isRead(entry) && last && last.sessionUpdate === "tool_call" && isRead(last)) {
      rows[rows.length - 1] = { sessionUpdate: "reads", _meta: { id: `${last._meta.id}+` }, calls: [last, entry as ToolCall] };
    } else rows.push(entry);
  });
  return rows;
}

const isTool = (row: Row) => row.sessionUpdate === "tool_call" || row.sessionUpdate === "reads";

export function AgentSessionView({ session, onShowTerminal }: { session: AgentSession; onShowTerminal: () => void }) {
  const rows = useMemo(() => rowsOf(session.entries), [session.entries]);
  const ref = useRef<HTMLDivElement | null>(null);
  const following = useRef(true);
  useLayoutEffect(() => {
    const el = ref.current;
    if (el && following.current) el.scrollTop = el.scrollHeight;
  }, [rows]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div
        ref={ref}
        onScroll={(e) => {
          const el = e.currentTarget;
          following.current = el.scrollHeight - el.scrollTop - el.clientHeight <= FOLLOW_SLACK_PX;
        }}
        aria-label="What it's doing"
        className="min-h-0 flex-1 overflow-auto px-4 py-3"
      >
        {session.earlier && (
          <p className="mb-2 text-center text-micro text-faint">Earlier in this session is in its terminal.</p>
        )}
        {rows.map((row, i) => (
          // Tool calls in a row sit close together; anything else gets room.
          <div key={row._meta.id} className={i === 0 ? "" : isTool(row) && isTool(rows[i - 1]) ? "mt-0.5" : "mt-2.5"}>
            <RowView row={row} />
          </div>
        ))}
      </div>
      <Now session={session} onShowTerminal={onShowTerminal} />
    </div>
  );
}

function RowView({ row, nested = false }: { row: Row; nested?: boolean }) {
  switch (row.sessionUpdate) {
    case "reads":
      return <ReadsRow calls={row.calls} />;
    case "tool_call":
      return <ToolRow call={row} />;
    case "plan":
      return <PlanView plan={row} />;
    case "user_message":
      return row._meta.from === "wake" ? (
        <Fold icon={Bell} label="Woken by the room" detail={textOf(row.content)} mono />
      ) : (
        <Prompt text={textOf(row.content)} queued={row._meta.queued} nested={nested} />
      );
    case "agent_message":
      return (
        <div className="text-label leading-relaxed text-text [&_p]:my-1">
          <MarkdownContent>{textOf(row.content)}</MarkdownContent>
        </div>
      );
    case "agent_thought": {
      const text = textOf(row.content);
      return text ? <Fold icon={Brain} label="Thought it through" detail={text} italic /> : null;
    }
    case "compaction":
      return (
        <p className="flex items-center gap-2 text-micro text-faint before:h-px before:flex-1 before:bg-border after:h-px after:flex-1 after:bg-border">
          Older context summarized
        </p>
      );
  }
}

/** How many lines of a prompt show before "Show all": a pasted file shouldn't fill the window. */
const PROMPT_LINES = 8;

function Prompt({ text, queued, nested }: { text: string; queued?: boolean; nested: boolean }) {
  const [all, setAll] = useState(false);
  const lines = text.split("\n");
  const long = lines.length > PROMPT_LINES || text.length > PROMPT_LINES * 120;
  const shown = long && !all ? lines.slice(0, PROMPT_LINES).join("\n").slice(0, PROMPT_LINES * 120) : text;
  return (
    <div className={cn("rounded-lg bg-hairline px-3 py-2 text-label text-text", nested && "bg-transparent px-0 py-0")}>
      {queued && <span className="mr-2 text-micro text-faint">queued</span>}
      <span className="break-words whitespace-pre-wrap">{shown}</span>
      {long && (
        <button
          type="button"
          onClick={() => setAll((a) => !a)}
          className="mt-1 block text-micro text-muted-foreground hover:text-text"
        >
          {all ? "Show less" : `Show all ${lines.length} lines`}
        </button>
      )}
    </div>
  );
}

/** A quiet line that opens to more. */
function Fold({
  icon: Icon,
  label,
  detail,
  mono,
  italic,
}: {
  icon: typeof Wrench;
  label: string;
  detail: string;
  mono?: boolean;
  italic?: boolean;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1.5 text-micro text-faint hover:text-muted-foreground"
      >
        <Icon className="size-3.5" aria-hidden />
        {label}
        <ChevronRight className={cn("size-3 transition-transform", open && "rotate-90")} aria-hidden />
      </button>
      {open && (
        <p
          className={cn(
            "mt-1 ml-5 border-l border-border pl-3 text-micro whitespace-pre-wrap text-muted-foreground",
            mono && "font-mono",
            italic && "italic",
          )}
        >
          {detail}
        </p>
      )}
    </div>
  );
}

const STEP_ICON = { pending: Circle, in_progress: CircleDot, completed: CircleCheck } as const;

/** The agent's steps, the one it's on marked. */
function PlanView({ plan }: { plan: Plan }) {
  const done = plan.entries.filter((e) => e.status === "completed").length;
  return (
    <div className="rounded-lg border border-border px-3 py-2">
      <p className="mb-1 flex items-center gap-1.5 text-micro text-faint">
        <ListChecks className="size-3.5" aria-hidden />
        <span className="tabular">
          {done}/{plan.entries.length}
        </span>
      </p>
      <ul className="space-y-0.5">
        {plan.entries.map((step, i) => {
          const Icon = STEP_ICON[step.status];
          return (
            <li key={i} className="flex items-start gap-2 text-label">
              <Icon
                className={cn(
                  "mt-0.5 size-3.5 flex-shrink-0",
                  step.status === "in_progress" ? "text-accent" : "text-faint",
                )}
                aria-label={step.status.replace("_", " ")}
              />
              <span
                className={cn(
                  step.status === "completed" ? "text-faint line-through decoration-faint/50" : "text-text",
                  step.status === "in_progress" && "font-medium",
                )}
              >
                {step.content}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function seconds(call: ToolCall): string | null {
  if (!call._meta.endedAt) return null;
  const s = (Date.parse(call._meta.endedAt) - Date.parse(call._meta.at)) / 1000;
  return s < 1 ? null : s < 60 ? `${Math.round(s)}s` : `${Math.round(s / 60)}m`;
}

function Status({ call }: { call: ToolCall }) {
  if (call.status === "pending" || call.status === "in_progress")
    return <Loader2 className="size-3.5 animate-spin text-accent" aria-label="Running" />;
  if (call.status === "failed")
    return call._meta.interrupted ? (
      <X className="size-3.5 text-faint" aria-label="Stopped" />
    ) : (
      <X className="size-3.5 text-red" aria-label="Failed" />
    );
  const took = seconds(call);
  return took ? (
    <span className="text-micro text-faint tabular">{took}</span>
  ) : (
    <Check className="size-3.5 text-faint" aria-label="Done" />
  );
}

/** A title that's a path, a pattern or the command itself, drawn as code; a sentence about it isn't. */
function codeLike(call: ToolCall): boolean {
  const command = (call.rawInput as { command?: unknown } | undefined)?.command;
  return !/\s/.test(call.title) || call.title === command || (call.locations ?? []).some((l) => call.title.includes(l.path));
}

function ToolRow({ call }: { call: ToolCall }) {
  const [open, setOpen] = useState(false);
  const [json, setJson] = useState(false);
  const sub = call._meta.subagent;
  const Icon = sub ? Bot : call._meta.from === "person" ? UserRound : TOOL_ICON[call.kind];
  const failed = call.status === "failed" && !call._meta.interrupted;
  const diffs = useMemo(
    () =>
      (call.content ?? []).flatMap((c) => (c.type === "diff" ? [{ path: c.path, ...diffLines(c.oldText, c.newText) }] : [])),
    [call.content],
  );
  const result = (call.content ?? []).flatMap((c) => (c.type === "content" ? [c.content.text] : [])).join("\n");
  const added = diffs.reduce((n, d) => n + d.added, 0);
  const removed = diffs.reduce((n, d) => n + d.removed, 0);
  const steps = sub?.entries.filter((e) => e.sessionUpdate === "tool_call").length ?? 0;
  return (
    <div className={cn("rounded-md border", open ? "border-border" : "border-transparent")}>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className={cn("flex h-7 w-full items-center gap-2 rounded-md px-2 text-left hover:bg-hairline", failed && "text-red")}
      >
        <Icon className={cn("size-3.5 flex-shrink-0", failed ? "text-red" : "text-muted-foreground")} aria-hidden />
        {sub ? (
          <span className="min-w-0 flex-1 truncate text-label text-text">{sub.description}</span>
        ) : codeLike(call) ? (
          <span className="min-w-0 flex-1 truncate font-mono text-micro text-text/90">{call.title}</span>
        ) : (
          <span className="min-w-0 flex-1 truncate text-label text-text/90">{call.title}</span>
        )}
        {diffs.length > 0 && (
          <span className="flex-shrink-0 font-mono text-micro tabular">
            {added > 0 && <span className="text-green">+{added}</span>}
            {added > 0 && removed > 0 && " "}
            {removed > 0 && <span className="text-red">−{removed}</span>}
          </span>
        )}
        {steps > 0 && <span className="flex-shrink-0 text-micro text-faint tabular">{steps} steps</span>}
        <span className="flex w-8 flex-shrink-0 justify-end">
          <Status call={call} />
        </span>
      </button>
      {open && (
        <div className="space-y-2 px-2 pt-1 pb-2">
          {sub ? (
            <div className="space-y-2 border-l border-border pl-3">
              {rowsOf(sub.entries).map((row) => (
                <RowView key={row._meta.id} row={row} nested />
              ))}
            </div>
          ) : null}
          {diffs.map((d) => (
            <pre key={d.path} className="max-h-56 overflow-auto rounded bg-bg px-2 py-1.5 font-mono text-micro leading-snug">
              {d.lines.map((line, i) => (
                <div
                  key={i}
                  className={cn(
                    "whitespace-pre",
                    line.startsWith("+") ? "bg-green/10 text-green" : line.startsWith("-") ? "bg-red/10 text-red" : "text-faint",
                  )}
                >
                  {line}
                </div>
              ))}
            </pre>
          ))}
          {result && (
            <pre className="max-h-56 overflow-auto rounded bg-bg px-2 py-1.5 font-mono text-micro leading-snug whitespace-pre-wrap text-muted-foreground">
              {result}
            </pre>
          )}
          {(call.rawInput !== undefined || call.rawOutput !== undefined) && (
            <button
              type="button"
              onClick={() => setJson((j) => !j)}
              aria-pressed={json}
              className="flex items-center gap-1 rounded px-1 text-micro text-faint hover:bg-hairline hover:text-muted-foreground"
            >
              <Braces className="size-3" aria-hidden />
              {call.name ?? call.kind}
            </button>
          )}
          {json && (
            <pre className="max-h-64 overflow-auto rounded bg-bg px-2 py-1.5 font-mono text-[11px] leading-snug text-muted-foreground">
              {JSON.stringify({ input: call.rawInput, output: call.rawOutput }, null, 2)}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

function ReadsRow({ calls }: { calls: ToolCall[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="flex h-7 w-full items-center gap-2 rounded-md px-2 text-left hover:bg-hairline"
      >
        <FileText className="size-3.5 flex-shrink-0 text-muted-foreground" aria-hidden />
        <span className="min-w-0 flex-1 truncate text-label text-text/90">Read {calls.length} files</span>
        <ChevronRight className={cn("size-3 text-faint transition-transform", open && "rotate-90")} aria-hidden />
      </button>
      {open && (
        <div className="ml-5">
          {calls.map((c) => (
            <ToolRow key={c._meta.id} call={c} />
          ))}
        </div>
      )}
    </div>
  );
}

/** The bottom line: what it's doing now, and what only its terminal shows. */
function Now({ session, onShowTerminal }: { session: AgentSession; onShowTerminal: () => void }) {
  if (session.state === "waiting") {
    return (
      <div className="flex items-center gap-2 border-t border-yellow/40 bg-yellow/10 px-4 py-2 text-label">
        <MessageCircleQuestion className="size-4 flex-shrink-0 text-yellow" aria-hidden />
        <span className="min-w-0 flex-1 truncate text-text">{session.waitingOn ?? "Waiting for an answer"}</span>
        <button
          type="button"
          onClick={onShowTerminal}
          className="flex-shrink-0 rounded px-2 py-0.5 text-micro font-medium text-accent hover:bg-hairline"
        >
          Answer in its terminal
        </button>
      </div>
    );
  }
  if (session.state === "working") {
    return (
      <div className="flex items-center gap-2 border-t border-border px-4 py-1.5 text-micro text-muted-foreground">
        <Loader2 className="size-3 animate-spin text-accent" aria-hidden />
        Working
      </div>
    );
  }
  // Idle, or a pane this CLI's state can't be read from: nothing to say.
  return null;
}

/** The rendered side with nothing to draw, and the way to the terminal, which always works. */
export function SessionUnavailable({
  reason,
  cli,
  onShowTerminal,
}: {
  reason: Unavailable;
  cli: string | null;
  onShowTerminal: () => void;
}) {
  const name = cli ?? "this agent's CLI";
  return (
    <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 px-8 text-center">
      <FileSearch className="size-6 text-faint" aria-hidden />
      <p className="max-w-xs text-label text-muted-foreground">
        {reason === "no_converter"
          ? `Mycelium can't read ${name} sessions yet.`
          : `Mycelium can't find where ${name} keeps this session.`}
      </p>
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={onShowTerminal}
          className="flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1 text-micro text-text hover:bg-hairline"
        >
          <SquareTerminal className="size-3.5" aria-hidden />
          Show its terminal
        </button>
        {reason === "no_converter" && (
          <a
            href={ADD_SESSION_SUPPORT_URL}
            target="_blank"
            rel="noreferrer"
            className="text-micro text-accent hover:underline"
          >
            Add support
          </a>
        )}
      </div>
    </div>
  );
}
