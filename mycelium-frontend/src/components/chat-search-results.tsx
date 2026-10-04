// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { ArrowDownUp } from "lucide-react";
import { HighlightText } from "@/components/ui/highlight-text";
import { Tooltip } from "@/components/ui/tooltip";
import {
  SORTS,
  hasClause,
  toggleClause,
  withSort,
  type FacetBucket,
  type MessageSearchHit,
  type MessageSearchResponse,
} from "@/lib/message-search";
import { nameOf, useNames } from "@/lib/people";
import { cn } from "@/lib/utils";

/** The fields offered as switches, in the order a reader narrows by. The rest
 *  are still in the grammar, and the find bar's hints offer them. */
const FACETS = ["from", "task", "in", "stance", "has", "day"] as const;

/** Values shown per field; a value already in the query is always shown. */
const PER_FIELD = 3;

interface Props {
  query: string;
  onQueryChange: (query: string) => void;
  result: MessageSearchResponse | null;
  failed: boolean;
  /** The words and phrases the hits are marked by. */
  needles: readonly string[];
  onOpenHit: (hit: MessageSearchHit) => void;
}

/**
 * The find bar's reach into the whole room: one line of counts to narrow by,
 * then one line per message the query matches, however far back and in
 * whichever thread. A count is a switch — on adds `field:value` to the
 * query, off takes it out — so the query in the bar always says what is
 * shown. A field whose matches all share one value narrows nothing, so it
 * isn't offered.
 */
export function ChatSearchResults({ query, onQueryChange, result, failed, needles, onOpenHit }: Props) {
  const names = useNames();
  if (failed && !result) {
    return (
      <Panel>
        <p className="px-4 py-2 text-micro text-red">Hub unreachable: only loaded messages were searched.</p>
      </Panel>
    );
  }
  if (!result) return null;

  const sort = result.scope.sort;
  const next = SORTS[(SORTS.indexOf(sort) + 1) % SORTS.length];
  const groups = FACETS.map((field) => {
    const buckets = result.facets[field] ?? [];
    const on = buckets.filter((b) => hasClause(query, field, b.value));
    const useful = buckets.length > 1 ? buckets : [];
    const shown = [...on, ...useful.filter((b) => !on.includes(b))].slice(0, Math.max(PER_FIELD, on.length));
    return { field, shown };
  }).filter((g) => g.shown.length > 0);

  return (
    <Panel>
      <div className="flex items-start gap-2 border-b border-border px-4 py-1.5 text-micro">
        <span className="shrink-0 py-px tabular text-muted-foreground">
          <span className="font-medium text-text">{result.total}</span> of {result.scanned}
        </span>
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-2.5 gap-y-1">
          {groups.map(({ field, shown }) => (
            <span key={field} className="flex items-center gap-1">
              <span className="font-mono text-faint">{field}</span>
              {shown.map((b) => (
                <Chip
                  key={b.value}
                  field={field}
                  bucket={b}
                  label={(field === "from" && nameOf(names, b.value)) || b.label}
                  on={hasClause(query, field, b.value)}
                  onClick={() => onQueryChange(toggleClause(query, field, b.value))}
                />
              ))}
            </span>
          ))}
        </div>
        <Tooltip content={`Sorted ${sort} first · click for ${next}`}>
          <button
            type="button"
            onClick={() => onQueryChange(withSort(query, next))}
            aria-label={`Sort: ${sort}`}
            className="flex shrink-0 items-center gap-1 rounded px-1 py-px capitalize text-muted-foreground transition-colors hover:bg-hairline hover:text-text"
          >
            <ArrowDownUp aria-hidden className="size-3" />
            {sort}
          </button>
        </Tooltip>
      </div>
      {result.hits.length === 0 ? (
        <p className="px-4 py-2 text-micro text-muted-foreground">No matches</p>
      ) : (
        <ul aria-label="Matching messages">
          {result.hits.map((hit) => (
            <li key={hit.message.id}>
              <HitRow hit={hit} needles={needles} onOpen={() => onOpenHit(hit)} name={nameOf(names, hit.message.sender_handle)} />
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function Panel({ children }: { children: React.ReactNode }) {
  return (
    <section
      aria-label="Search the room's history"
      data-slot="chat-search-results"
      className="max-h-[40%] shrink-0 overflow-y-auto border-b border-border bg-surface/60"
    >
      {children}
    </section>
  );
}

function Chip({
  field,
  bucket,
  label,
  on,
  onClick,
}: {
  field: string;
  bucket: FacetBucket;
  label: string;
  on: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={on}
      title={`${field}:${bucket.value}`}
      onClick={onClick}
      className={cn(
        "flex max-w-40 items-baseline gap-1 rounded px-1.5 py-px transition-colors",
        on ? "bg-accent-soft text-accent" : "text-muted-foreground hover:bg-hairline hover:text-text",
      )}
    >
      <span className="truncate">{label}</span>
      <span className="tabular opacity-60">{bucket.count}</span>
    </button>
  );
}

function when(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "";
  return at.toDateString() === new Date().toDateString()
    ? at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : at.toLocaleDateString([], { month: "short", day: "numeric" });
}

/** One line: who, the task it was said in (if any), what was said, when. */
function HitRow({
  hit,
  needles,
  onOpen,
  name,
}: {
  hit: MessageSearchHit;
  needles: readonly string[];
  onOpen: () => void;
  name: string | null | undefined;
}) {
  const where = hit.task_title ?? (hit.thread ? "thread" : null);
  return (
    <button
      type="button"
      onClick={onOpen}
      className="flex w-full items-baseline gap-2 px-4 py-1 text-left text-label transition-colors hover:bg-hairline"
    >
      <span className="max-w-32 shrink-0 truncate font-medium text-text">{name || hit.message.sender_handle}</span>
      {where && <span className="max-w-48 shrink-0 truncate text-micro text-accent">{where}</span>}
      <span className="min-w-0 flex-1 truncate text-muted-foreground">
        <HighlightText text={hit.snippet} highlight={needles.length ? { query: needles } : undefined} />
      </span>
      <span className="shrink-0 text-micro tabular text-faint">{when(hit.message.created_at)}</span>
    </button>
  );
}
