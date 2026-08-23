// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import type { ReactNode } from "react";
import {
  Ban,
  Bot,
  CircleDot,
  CircleHelp,
  Eye,
  GitBranch,
  GitPullRequest,
  Radio,
  TriangleAlert,
  UserRound,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  arr,
  bool,
  formatAge,
  kindOf,
  priorityOf,
  statusOf,
  str,
  ttlSpent,
  type ItemKind,
  type LiveItem,
  type Priority,
} from "@/lib/board/item";

/** One glyph + colour per row kind — the cockpit's fastest read. */
const KIND_STYLE: Record<ItemKind, { icon: typeof CircleDot; color: string; label: string }> = {
  decision: { icon: CircleHelp, color: "var(--accent)", label: "decision" },
  blocked: { icon: Ban, color: "var(--red)", label: "blocked" },
  review: { icon: Eye, color: "var(--yellow)", label: "review" },
  action: { icon: CircleDot, color: "var(--green)", label: "action" },
  concern: { icon: TriangleAlert, color: "var(--yellow)", label: "concern" },
  signal: { icon: Radio, color: "var(--muted-foreground)", label: "signal" },
};

export function KindGlyph({ item, className }: { item: LiveItem; className?: string }) {
  const style = KIND_STYLE[kindOf(item)];
  const Icon = style.icon;
  return (
    <span
      title={style.label}
      className={cn("flex size-5 shrink-0 items-center justify-center", className)}
      style={{ color: style.color }}
    >
      <Icon className="size-4" strokeWidth={1.9} />
    </span>
  );
}

export function kindColor(item: LiveItem): string {
  return KIND_STYLE[kindOf(item)].color;
}

const PRIORITY_STYLE: Record<Priority, { color: string; bars: number }> = {
  urgent: { color: "var(--red)", bars: 3 },
  high: { color: "var(--yellow)", bars: 2 },
  normal: { color: "var(--muted-foreground)", bars: 1 },
  low: { color: "var(--faint)", bars: 1 },
};

/** Priority as a three-bar meter: readable at a glance, quiet at rest. */
export function PriorityMeter({ item }: { item: LiveItem }) {
  const priority = priorityOf(item);
  const { color, bars } = PRIORITY_STYLE[priority];
  return (
    <span title={`priority: ${priority}`} className="flex items-end gap-[2px]" aria-hidden>
      {[0, 1, 2].map(i => (
        <span
          key={i}
          className="w-[3px] rounded-[1px]"
          style={{
            height: `${5 + i * 3}px`,
            background: i < bars ? color : "var(--border2)",
            opacity: priority === "low" && i === 0 ? 0.6 : 1,
          }}
        />
      ))}
    </span>
  );
}

export function StatusPill({ item }: { item: LiveItem }) {
  const status = statusOf(item);
  const tone: Record<string, string> = {
    open: "var(--accent)",
    claimed: "var(--accent)",
    in_progress: "var(--accent)",
    in_review: "var(--yellow)",
    blocked: "var(--red)",
    resolved: "var(--green)",
    dismissed: "var(--faint)",
  };
  const color = tone[status] ?? "var(--muted-foreground)";
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 font-mono text-micro"
      style={{ background: `color-mix(in srgb, ${color} 12%, transparent)`, color }}
    >
      <span className="size-1.5 rounded-full" style={{ background: color }} />
      {status.replace("_", " ")}
    </span>
  );
}

/** An owner reads the same whether it's a person or an agent — peers on one board. */
export function OwnerChip({ handle, live }: { handle: string | null; live?: boolean }) {
  if (!handle) {
    return (
      <span className="inline-flex items-center gap-1 text-micro text-faint">
        <UserRound className="size-3" strokeWidth={1.8} />
        unowned
      </span>
    );
  }
  const isAgent = /agent|aligner|synthesizer|growth|risk|finance/i.test(handle);
  const Icon = isAgent ? Bot : UserRound;
  const color = isAgent ? "var(--accent)" : "var(--muted-foreground)";
  return (
    <span className="inline-flex items-center gap-1 text-micro" style={{ color }}>
      <Icon className="size-3" strokeWidth={1.8} />
      <span className="font-mono">@{handle.replace(/^@/, "")}</span>
      {live && <span className="size-1.5 animate-pulse rounded-full bg-accent" title="resident" />}
    </span>
  );
}

const CI_TONE: Record<string, string> = {
  green: "var(--green)",
  running: "var(--yellow)",
  red: "var(--red)",
};

/**
 * How a provider's answer reads. `done` is deliberately quiet: a merged pull
 * request is finished, and a board that shouts about finished work buries the
 * work that isn't.
 */
const UPSTREAM_TONE: Record<string, string> = {
  failed: "var(--red)",
  blocked: "var(--red)",
  pending: "var(--yellow)",
  ok: "var(--green)",
  done: "var(--muted-foreground)",
  unknown: "var(--muted-foreground)",
};

/**
 * A row that points somewhere but has no answer yet.
 *
 * The hub answers a read from cache and refreshes behind it, so the first look
 * at a room knows a task names a pull request without knowing what the pull
 * request says. A skeleton is the honest shape of that: it holds the space the
 * answer will take, so the row does not reflow when it lands, and it says
 * "coming" rather than showing a state nobody reported.
 */
function UpstreamSkeleton({ label }: { label: string | null }) {
  return (
    <span
      className="inline-flex items-center gap-1 font-mono text-micro text-faint"
      title={label ?? "checking upstream"}
      aria-busy="true"
      aria-label="checking upstream"
    >
      <span className="size-1.5 animate-pulse rounded-full bg-border2" />
      <span className="h-2 w-16 animate-pulse rounded-full bg-border2" />
    </span>
  );
}

/**
 * What the tool this row points at says about it, in that tool's own words.
 *
 * The provider's label is shown verbatim ("changes requested", "CI failing")
 * because that is the phrasing the reader already recognises; the state behind
 * it is what the board sorts and colours by. A stale answer wears its age, so a
 * reader is never asked to trust a number without knowing how old it is.
 */
export function UpstreamChip({ item }: { item: LiveItem }) {
  const state = str(item, "upstream");
  // No state and a pending marker means the answer is still coming, which is a
  // different thing from a row that points nowhere (nothing at all) and from
  // `unknown`, which is a provider saying it could not place what it found.
  if (!state) {
    return bool(item, "upstream_pending") ? (
      <UpstreamSkeleton label={str(item, "upstream_label")} />
    ) : null;
  }
  const label = str(item, "upstream_label") ?? state;
  const age = str(item, "upstream_age");
  const url = str(item, "upstream_url");
  const more = item.fields.upstream_count;
  const freshness = str(item, "upstream_freshness");
  const tone = UPSTREAM_TONE[state] ?? "var(--muted-foreground)";
  // A stale answer is still the truth as far as anyone knows; it just has a
  // refresh running behind it. Dimming it and pulsing the dot says that without
  // taking the value away, which a spinner in its place would.
  const aging = freshness === "stale" || freshness === "error";

  const body = (
    <>
      <span
        className={cn("size-1.5 rounded-full", aging && "animate-pulse")}
        style={{ background: tone }}
      />
      {label}
      {typeof more === "number" && more > 1 && (
        <span className="text-muted-foreground">+{more - 1}</span>
      )}
      {age && <span className="text-faint">{age}</span>}
    </>
  );

  const className = cn(
    "inline-flex items-center gap-1 font-mono text-micro transition-opacity",
    aging && "opacity-70",
  );
  return url ? (
    <a
      href={url}
      target="_blank"
      rel="noreferrer noopener"
      className={cn(className, "hover:underline")}
      style={{ color: tone }}
      title={`${state} upstream${aging ? `, ${freshness}` : ""}`}
    >
      {body}
    </a>
  ) : (
    <span
      className={className}
      style={{ color: tone }}
      title={`${state} upstream${aging ? `, ${freshness}` : ""}`}
    >
      {body}
    </span>
  );
}

/** The work-links strip: branch · CI · PR · issue, only what the row carries. */
export function WorkLinks({ item }: { item: LiveItem }) {
  const branch = str(item, "branch");
  const pr = str(item, "pr");
  const issue = str(item, "issue");
  const ci = str(item, "ci");
  if (!branch && !pr && !issue && !ci) return null;
  return (
    <span className="inline-flex flex-wrap items-center gap-x-2.5 gap-y-1">
      {branch && (
        <span className="inline-flex items-center gap-1 font-mono text-micro text-muted-foreground">
          <GitBranch className="size-3" strokeWidth={1.8} />
          {branch}
        </span>
      )}
      {ci && (
        <span
          className="inline-flex items-center gap-1 font-mono text-micro"
          style={{ color: CI_TONE[ci] ?? "var(--muted-foreground)" }}
          title={`CI ${ci}`}
        >
          <span
            className={cn("size-1.5 rounded-full", ci === "running" && "animate-pulse")}
            style={{ background: CI_TONE[ci] ?? "var(--muted-foreground)" }}
          />
          CI {ci}
        </span>
      )}
      {pr && (
        <span className="inline-flex items-center gap-1 font-mono text-micro text-muted-foreground">
          <GitPullRequest className="size-3" strokeWidth={1.8} />
          {pr}
        </span>
      )}
      {issue && !pr && (
        <span className="inline-flex items-center gap-1 font-mono text-micro text-muted-foreground">
          gh {issue}
        </span>
      )}
    </span>
  );
}

/**
 * How much of the row's TTL is spent. The bar is the honest expression of
 * "transient by design": a row nobody touches visibly drains rather than
 * silently aging into a backlog.
 */
/** Drawn only once the clock is worth looking at — an untouched row shouldn't
 *  wear a progress bar for two days before it means anything. */
const TTL_VISIBLE_FROM = 0.4;

export function TtlBar({ item, now }: { item: LiveItem; now: number }) {
  const spent = ttlSpent(item, now);
  if (spent === null || spent < TTL_VISIBLE_FROM) return null;
  const color = spent > 0.75 ? "var(--red)" : "var(--yellow)";
  return (
    <span
      className="block h-[2px] w-10 overflow-hidden rounded-full bg-hairline"
      title={`${Math.round(spent * 100)}% of its TTL spent`}
    >
      <span className="block h-full rounded-full" style={{ width: `${spent * 100}%`, background: color }} />
    </span>
  );
}

/** Where the row came from, always shown: no row on this board is unsourced. */
export function SourceTag({ item }: { item: LiveItem }) {
  return (
    <span className="truncate font-mono text-micro text-faint" title={item.source.label}>
      {item.source.label}
    </span>
  );
}

export function AgeTag({ item, now }: { item: LiveItem; now: number }) {
  const age = str(item, "updated") ?? str(item, "created");
  const minutes = age ? Math.max(0, Math.round((now - Date.parse(age)) / 60000)) : null;
  return (
    <span className="tabular text-micro text-faint" title={age ?? undefined}>
      {formatAge(Number.isFinite(minutes as number) ? minutes : null)}
    </span>
  );
}

export function BlocksNote({ item }: { item: LiveItem }) {
  const blocks = arr(item, "blocks");
  if (!blocks.length) return null;
  return (
    <span className="text-micro text-muted-foreground">
      blocks <span className="text-text">{blocks.join(", ")}</span>
    </span>
  );
}

export function LiveDot({ item }: { item: LiveItem }) {
  if (!bool(item, "live")) return null;
  return (
    <span className="inline-flex items-center gap-1 text-micro text-accent">
      <span className="size-1.5 animate-pulse rounded-full bg-accent" />
      live
    </span>
  );
}

export function Meta({ children }: { children: ReactNode }) {
  return <span className="inline-flex items-center gap-2 text-micro text-muted-foreground">{children}</span>;
}
