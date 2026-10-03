// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { MessageSquare, SquareKanban } from "lucide-react";
import { HighlightText } from "@/components/ui/highlight-text";
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

/** The fields worth a row of counts here, in the order a reader narrows by.
 *  The rest are still in the grammar, and the find bar's hints offer them. */
const FACET_ROWS: { field: string; label: string }[] = [
  { field: "from", label: "From" },
  { field: "task", label: "Task" },
  { field: "in", label: "Where" },
  { field: "stance", label: "Stance" },
  { field: "has", label: "Has" },
  { field: "day", label: "Day" },
];

const CHIPS_PER_ROW = 6;

interface Props {
  query: string;
  onQueryChange: (query: string) => void;
  result: MessageSearchResponse | null;
  loading: boolean;
  failed: boolean;
  /** The words and phrases the hits are marked by. */
  needles: readonly string[];
  onOpenHit: (hit: MessageSearchHit) => void;
}

/**
 * The find bar's reach into the whole room: every message the query matches,
 * however far back and in whichever thread, with counts per field to narrow
 * by. A count is a switch — clicking one adds `field:value` to the query, and
 * clicking it again takes it out — so narrowing never needs the grammar
 * typed, and the query in the bar always says what is being shown.
 */
export function ChatSearchResults({ query, onQueryChange, result, loading, failed, needles, onOpenHit }: Props) {
  const names = useNames();
  if (failed && !result) {
    return (
      <Panel>
        <p className="px-4 py-3 text-micro text-red">The hub didn&apos;t answer, so only the loaded messages were searched.</p>
      </Panel>
    );
  }
  if (!result) {
    return (
      <Panel>
        <p className="px-4 py-3 text-micro text-muted-foreground">{loading ? "Searching the room…" : ""}</p>
      </Panel>
    );
  }

  const sort = result.scope.sort;
  const rows = FACET_ROWS.filter((r) => (result.facets[r.field] ?? []).length > 0);
  return (
    <Panel>
      <div className={cn("flex flex-col gap-1 border-b border-border px-4 py-2 transition-opacity", loading && "opacity-60")}>
        <div className="flex items-center gap-2 text-micro text-muted-foreground">
          <span>
            <span className="tabular font-medium text-text">{result.total}</span>{" "}
            {result.total === 1 ? "message" : "messages"} of {result.scanned} in this room
          </span>
          <div role="radiogroup" aria-label="Order" className="ml-auto flex items-center gap-0.5">
            {SORTS.map((s) => (
              <button
                key={s}
                type="button"
                role="radio"
                aria-checked={sort === s}
                onClick={() => onQueryChange(withSort(query, s))}
                className={cn(
                  "rounded px-1.5 py-0.5 capitalize transition-colors",
                  sort === s ? "bg-hairline text-text" : "hover:text-text",
                )}
              >
                {s}
              </button>
            ))}
          </div>
        </div>
        {rows.map(({ field, label }) => (
          <FacetRow
            key={field}
            field={field}
            label={label}
            buckets={result.facets[field]}
            query={query}
            onQueryChange={onQueryChange}
            nameFor={field === "from" ? (h) => nameOf(names, h) : undefined}
          />
        ))}
      </div>
      {result.hits.length === 0 ? (
        <p className="px-4 py-3 text-micro text-muted-foreground">No message in the room matches.</p>
      ) : (
        <ul aria-label="Matching messages" className="divide-y divide-border/60">
          {result.hits.map((hit) => (
            <li key={hit.message.id}>
              <HitRow hit={hit} needles={needles} onOpen={() => onOpenHit(hit)} name={nameOf(names, hit.message.sender_handle)} />
            </li>
          ))}
        </ul>
      )}
      {result.total > result.hits.length && (
        <p className="border-t border-border px-4 py-2 text-micro text-muted-foreground">
          The newest {result.hits.length} of {result.total}. Narrow with the counts above.
        </p>
      )}
    </Panel>
  );
}

function Panel({ children }: { children: React.ReactNode }) {
  return (
    <section
      aria-label="Search the room's history"
      data-slot="chat-search-results"
      className="max-h-[45%] shrink-0 overflow-y-auto border-b border-border bg-surface/60"
    >
      {children}
    </section>
  );
}

function FacetRow({
  field,
  label,
  buckets,
  query,
  onQueryChange,
  nameFor,
}: {
  field: string;
  label: string;
  buckets: FacetBucket[];
  query: string;
  onQueryChange: (query: string) => void;
  nameFor?: (value: string) => string | null | undefined;
}) {
  const shown = field === "day" ? [...buckets].sort((a, b) => b.value.localeCompare(a.value)) : buckets;
  return (
    <div className="flex items-baseline gap-2 text-micro">
      <span className="w-12 shrink-0 text-faint">{label}</span>
      <div className="flex min-w-0 flex-wrap gap-1">
        {shown.slice(0, CHIPS_PER_ROW).map((b) => {
          const on = hasClause(query, field, b.value);
          const text = nameFor?.(b.value) || b.label;
          return (
            <button
              key={b.value}
              type="button"
              aria-pressed={on}
              title={`${field}:${b.value}`}
              onClick={() => onQueryChange(toggleClause(query, field, b.value))}
              className={cn(
                "flex max-w-48 items-baseline gap-1 rounded-full border px-2 py-px transition-colors",
                on
                  ? "border-accent/50 bg-accent-soft text-accent"
                  : "border-border text-muted-foreground hover:border-border2 hover:text-text",
              )}
            >
              <span className="truncate">{text}</span>
              <span className="tabular opacity-70">{b.count}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function when(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "";
  const today = new Date();
  const sameDay = at.toDateString() === today.toDateString();
  return sameDay
    ? at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : at.toLocaleDateString([], { month: "short", day: "numeric" });
}

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
  const where = hit.task_title ?? (hit.thread ? "a thread" : null);
  return (
    <button
      type="button"
      onClick={onOpen}
      className="flex w-full flex-col gap-0.5 px-4 py-1.5 text-left transition-colors hover:bg-hairline"
    >
      <span className="flex min-w-0 items-center gap-1.5 text-micro">
        <span className="truncate font-medium text-text">{name || hit.message.sender_handle}</span>
        {where ? (
          <span className="flex min-w-0 items-center gap-1 rounded bg-hairline px-1.5 text-muted-foreground">
            <SquareKanban aria-hidden className="size-3 shrink-0" />
            <span className="truncate">{where}</span>
          </span>
        ) : (
          <span className="flex items-center gap-1 text-faint">
            <MessageSquare aria-hidden className="size-3" />
            in the room
          </span>
        )}
        {hit.stance && (
          <span className={cn("rounded px-1", hit.stance === "accept" ? "text-green" : "text-red")}>{hit.stance}</span>
        )}
        <span className="ml-auto shrink-0 tabular text-faint">{when(hit.message.created_at)}</span>
      </span>
      <span className="line-clamp-2 text-label text-muted-foreground">
        <HighlightText text={hit.snippet} highlight={needles.length ? { query: needles } : undefined} />
      </span>
    </button>
  );
}
