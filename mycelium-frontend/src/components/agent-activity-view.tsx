// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * An agent's session drawn as what it did rather than as its screen: what it
 * was asked, what it said, and each tool it called with how that went. It is
 * the other side of the terminal window's toggle, and reads the same session
 * from the same machine (`lib/agent-activity.ts`).
 *
 * A tool call is one line, and opens to its result, its change, and the call
 * as the CLI wrote it. Reads in a row fold into one line. A sub-agent's work
 * opens beneath its call. What only the terminal shows, such as a permission
 * prompt, is said at the bottom with the way back to the terminal.
 */

import { useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  Bell,
  Bot,
  Brain,
  Check,
  ChevronRight,
  Braces,
  FilePen,
  FilePlus,
  FileText,
  Globe,
  Loader2,
  MessageCircleQuestion,
  Search,
  SquareTerminal,
  Wrench,
  X,
} from "lucide-react";
import type { ActivityItem, AgentActivity, ToolCall, ToolKind } from "@/lib/agent-activity";
import { MarkdownContent } from "@/components/markdown-content";
import { cn } from "@/lib/utils";

const TOOL_ICON: Record<ToolKind, typeof Wrench> = {
  command: SquareTerminal,
  read: FileText,
  edit: FilePen,
  write: FilePlus,
  search: Search,
  web: Globe,
  agent: Bot,
  question: MessageCircleQuestion,
  other: Wrench,
};

/** How close to the bottom, in pixels, still counts as following along. */
const FOLLOW_SLACK_PX = 24;

/** Consecutive reads, folded into one line. */
type Row = ActivityItem | { kind: "reads"; id: string; calls: ToolCall[] };

function rowsOf(items: ActivityItem[]): Row[] {
  const rows: Row[] = [];
  for (const item of items) {
    const last = rows.at(-1);
    const isRead = item.kind === "tool" && item.tool === "read" && item.status !== "failed";
    if (isRead && last?.kind === "reads") last.calls.push(item);
    else if (isRead && last?.kind === "tool" && last.tool === "read" && last.status !== "failed") {
      rows[rows.length - 1] = { kind: "reads", id: `${last.id}+`, calls: [last, item] };
    } else rows.push(item);
  }
  return rows;
}

const isTool = (row: Row) => row.kind === "tool" || row.kind === "reads";

export function AgentActivityView({
  activity,
  onShowTerminal,
}: {
  activity: AgentActivity;
  onShowTerminal: () => void;
}) {
  const rows = useMemo(() => rowsOf(activity.items), [activity.items]);
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
        {activity.earlier && (
          <p className="mb-2 text-center text-micro text-faint">Earlier in this session is in its terminal.</p>
        )}
        {rows.map((row, i) => (
          // Tool calls in a row sit close together; anything else gets room.
          <div key={row.id} className={i === 0 ? "" : isTool(row) && isTool(rows[i - 1]) ? "mt-0.5" : "mt-2.5"}>
            <RowView row={row} />
          </div>
        ))}
      </div>
      <Now activity={activity} onShowTerminal={onShowTerminal} />
    </div>
  );
}

function RowView({ row, nested = false }: { row: Row; nested?: boolean }) {
  switch (row.kind) {
    case "reads":
      return <ReadsRow calls={row.calls} />;
    case "tool":
      return <ToolRow call={row} />;
    case "prompt":
      return row.from === "wake" ? (
        <Fold icon={Bell} label="Woken by the room" detail={row.text} mono />
      ) : (
        <div className={cn("rounded-lg bg-hairline px-3 py-2 text-label text-text", nested && "bg-transparent px-0 py-0")}>
          {row.queued && <span className="mr-2 text-micro text-faint">queued</span>}
          <span className="whitespace-pre-wrap">{row.text}</span>
        </div>
      );
    case "reply":
      return (
        <div className="text-label leading-relaxed text-text [&_p]:my-1">
          <MarkdownContent>{row.text}</MarkdownContent>
        </div>
      );
    case "thinking":
      return row.text ? <Fold icon={Brain} label="Thought it through" detail={row.text} italic /> : null;
    case "marker":
      return (
        <p className="flex items-center gap-2 text-micro text-faint before:h-px before:flex-1 before:bg-border after:h-px after:flex-1 after:bg-border">
          {row.what === "compacted" ? "Older context summarized" : row.what === "interrupted" ? "Interrupted" : "Resumed"}
        </p>
      );
  }
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

function seconds(call: ToolCall): string | null {
  if (!call.ended_at) return null;
  const s = (Date.parse(call.ended_at) - Date.parse(call.at)) / 1000;
  return s < 1 ? null : s < 60 ? `${Math.round(s)}s` : `${Math.round(s / 60)}m`;
}

function Status({ call }: { call: ToolCall }) {
  if (call.status === "running") return <Loader2 className="size-3.5 animate-spin text-accent" aria-label="Running" />;
  if (call.status === "failed") return <X className="size-3.5 text-red" aria-label="Failed" />;
  if (call.status === "interrupted") return <X className="size-3.5 text-faint" aria-label="Interrupted" />;
  const took = seconds(call);
  return took ? (
    <span className="text-micro text-faint tabular">{took}</span>
  ) : (
    <Check className="size-3.5 text-faint" aria-label="Done" />
  );
}

function ToolRow({ call }: { call: ToolCall }) {
  const [open, setOpen] = useState(false);
  const [json, setJson] = useState(false);
  const Icon = TOOL_ICON[call.tool];
  const steps = call.agent?.items.filter((i) => i.kind === "tool").length ?? 0;
  return (
    <div className={cn("rounded-md border", open ? "border-border" : "border-transparent")}>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "flex h-7 w-full items-center gap-2 rounded-md px-2 text-left hover:bg-hairline",
          call.status === "failed" && "text-red",
        )}
      >
        <Icon className={cn("size-3.5 flex-shrink-0", call.status === "failed" ? "text-red" : "text-muted-foreground")} aria-hidden />
        {call.tool === "agent" ? (
          <span className="min-w-0 flex-1 truncate text-label text-text">{call.agent?.description ?? call.summary}</span>
        ) : (
          <span className="min-w-0 flex-1 truncate font-mono text-micro text-text/90">{call.summary}</span>
        )}
        {call.change && (
          <span className="flex-shrink-0 font-mono text-micro tabular">
            {call.change.added > 0 && <span className="text-green">+{call.change.added}</span>}
            {call.change.added > 0 && call.change.removed > 0 && " "}
            {call.change.removed > 0 && <span className="text-red">−{call.change.removed}</span>}
          </span>
        )}
        {call.tool === "agent" && steps > 0 && <span className="flex-shrink-0 text-micro text-faint tabular">{steps} steps</span>}
        <span className="flex w-8 flex-shrink-0 justify-end">
          <Status call={call} />
        </span>
      </button>
      {open && (
        <div className="space-y-2 px-2 pt-1 pb-2">
          {call.agent ? (
            <div className="space-y-2 border-l border-border pl-3">
              {rowsOf(call.agent.items).map((row) => (
                <RowView key={row.id} row={row} nested />
              ))}
            </div>
          ) : call.change ? (
            <pre className="max-h-56 overflow-auto rounded bg-bg px-2 py-1.5 font-mono text-micro leading-snug">
              {call.change.lines.map((line, i) => (
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
          ) : call.result ? (
            <pre className="max-h-56 overflow-auto rounded bg-bg px-2 py-1.5 font-mono text-micro leading-snug whitespace-pre-wrap text-muted-foreground">
              {call.result}
            </pre>
          ) : null}
          <button
            type="button"
            onClick={() => setJson((j) => !j)}
            aria-pressed={json}
            className="flex items-center gap-1 rounded px-1 text-micro text-faint hover:bg-hairline hover:text-muted-foreground"
          >
            <Braces className="size-3" aria-hidden />
            {call.name}
          </button>
          {json && (
            <pre className="max-h-64 overflow-auto rounded bg-bg px-2 py-1.5 font-mono text-[11px] leading-snug text-muted-foreground">
              {JSON.stringify(call.raw, null, 2)}
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
            <ToolRow key={c.id} call={c} />
          ))}
        </div>
      )}
    </div>
  );
}

/** The bottom line: what it's doing now, and what only its terminal shows. */
function Now({ activity, onShowTerminal }: { activity: AgentActivity; onShowTerminal: () => void }) {
  if (activity.state === "waiting") {
    return (
      <div className="flex items-center gap-2 border-t border-yellow/40 bg-yellow/10 px-4 py-2 text-label">
        <MessageCircleQuestion className="size-4 flex-shrink-0 text-yellow" aria-hidden />
        <span className="min-w-0 flex-1 truncate text-text">{activity.waiting_on ?? "Waiting for an answer"}</span>
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
  if (activity.state === "working") {
    return (
      <div className="flex items-center gap-2 border-t border-border px-4 py-1.5 text-micro text-muted-foreground">
        <Loader2 className="size-3 animate-spin text-accent" aria-hidden />
        Working
      </div>
    );
  }
  return null;
}
