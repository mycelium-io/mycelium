// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";
import { FindBar } from "@/components/find-bar";
import { ChatSearchResults, Panel } from "@/components/chat-search-results";
import { HighlightText } from "@/components/ui/highlight-text";
import { searchMemories, type MemorySearchResult } from "@/lib/api";
import { stepIndex } from "@/lib/chat-search";
import { findRanges, markRanges, revealRange } from "@/lib/dom-find";
import { memoryTitle } from "@/lib/memory-preview";
import { freeText, type MessageSearchHit } from "@/lib/message-search";
import { useMessageSearch } from "@/lib/room-data";
import { cn } from "@/lib/utils";

/** How long typing pauses before the view is re-marked, and before the hub is asked. */
const FIND_SETTLE_MS = 120;
const SEARCH_SETTLE_MS = 200;
/** How long a view's own changes (a reply landing, a row re-rendering) settle before it is searched again. */
const RESCAN_MS = 150;

/** What History reaches from a view, past what the view has drawn. */
export type FindHistory =
  | {
      kind: "messages";
      room: string;
      /** The clauses every query here carries: `thread:<episode>` in a thread. */
      scope: string;
      about: string;
      onOpenHit: (hit: MessageSearchHit) => void;
    }
  | { kind: "memories"; room: string; onOpen: (key: string) => void };

interface Props {
  /** Bumped to open the bar (or re-select it): the room's ⌘F, for this view. */
  request: number;
  /** "Find in this memory". */
  label: string;
  history?: FindHistory;
  className?: string;
  /** Classes for the box around the view, under the bar. */
  contentClassName?: string;
  children: React.ReactNode;
}

/**
 * ⌘F for a view: the channel's find bar over whatever the view draws.
 *
 * It finds in the text on the page (`lib/dom-find.ts`): what a view shows is
 * what there is to find, whether that's a thread, a memory, the board or the
 * files. History reaches past it where the view has a search of its own: a
 * thread's messages, or the room's memories.
 */
export function Findable({ request, label, history, className, contentClassName, children }: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [standing, setStanding] = useState(0);
  const [historyOpen, setHistoryOpen] = useState(true);
  const input = useRef<HTMLInputElement>(null);
  const content = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!request) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- a key press, delivered as a counter
    setOpen(true);
  }, [request]);
  // A second ⌘F selects what's in the bar, so the key that opens a search starts a new one.
  useEffect(() => {
    if (!open) return;
    input.current?.focus();
    input.current?.select();
  }, [open, request]);

  // What's marked follows once typing pauses; what the hub is asked, a little later.
  const [applied, setApplied] = useState("");
  useEffect(() => {
    const next = open ? query : "";
    const timer = setTimeout(() => setApplied(next), next.trim() ? FIND_SETTLE_MS : 0);
    return () => clearTimeout(timer);
  }, [open, query]);
  const [settled, setSettled] = useState("");
  useEffect(() => {
    const next = open ? query : "";
    const timer = setTimeout(() => setSettled(next), next ? SEARCH_SETTLE_MS : 0);
    return () => clearTimeout(timer);
  }, [open, query]);
  const needles = useMemo(() => freeText(applied), [applied]);

  // The hits in what the view shows, found again whenever it changes under the bar.
  const [ranges, setRanges] = useState<Range[]>([]);
  useEffect(() => {
    const root = content.current;
    if (!open || !root || needles.length === 0) {
      setRanges([]);
      return;
    }
    const scan = () => setRanges(findRanges(root, needles));
    scan();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const observer = new MutationObserver(() => {
      clearTimeout(timer);
      timer = setTimeout(scan, RESCAN_MS);
    });
    observer.observe(root, { subtree: true, childList: true, characterData: true });
    return () => {
      observer.disconnect();
      clearTimeout(timer);
    };
  }, [open, needles]);

  // A view reads top down, so a new query stands on its first hit.
  const position = ranges.length === 0 ? null : Math.min(standing, ranges.length - 1);
  const active = position === null ? null : ranges[position];
  useEffect(() => markRanges(content, ranges, active), [ranges, active]);
  // Brought into view when the reader steps or the query changes, never when
  // the view re-renders under it: a reply landing mustn't pull the page away.
  const revealed = useRef<string | null>(null);
  useEffect(() => {
    const at = `${applied}#${position}`;
    if (!active || revealed.current === at) return;
    revealed.current = at;
    revealRange(active);
  }, [active, applied, position]);

  const step = (delta: 1 | -1) => {
    if (applied !== query) {
      setApplied(query);
      setStanding(0);
      return;
    }
    if (ranges.length === 0) return;
    setStanding(stepIndex(position ?? 0, ranges.length, delta));
  };
  const close = () => {
    setOpen(false);
    revealed.current = null;
  };

  // History: a thread's messages through the room's message search, or the room's memories.
  const asked = settled.trim();
  const messages = useMessageSearch(
    history?.kind === "messages" ? history.room : "",
    history?.kind === "messages" && asked ? `${history.scope} ${asked}` : "",
  );
  const memories = useSWR(
    history?.kind === "memories" && asked ? (["room", history.room, "memory-search", asked] as const) : null,
    ([, room, , q]) => searchMemories(room, q),
    { keepPreviousData: true, revalidateOnFocus: false },
  );
  const found =
    history?.kind === "messages"
      ? {
          total: messages.result?.total ?? null,
          loading: messages.loading,
          failed: Boolean(messages.error),
          problems: messages.result?.scope.problems ?? [],
        }
      : history?.kind === "memories"
        ? {
            total: asked ? (memories.data?.length ?? null) : null,
            loading: memories.isLoading || memories.isValidating,
            failed: Boolean(memories.error),
            problems: [],
          }
        : null;
  const showHistory = open && historyOpen && query.trim().length > 0 && history;

  return (
    <div className={cn("flex min-h-0 flex-col", className)}>
      {open && (
        <FindBar
          label={label}
          placeholder={history?.kind === "messages" ? "Find  ·  from:  after:" : "Find"}
          grammar={history?.kind === "messages"}
          countAbout="Matches in what's shown here"
          historyAbout={history?.kind === "messages" ? history.about : "Memories in the room that match, by meaning"}
          query={query}
          onQueryChange={value => {
            setQuery(value);
            setStanding(0);
          }}
          count={ranges.length}
          position={position}
          settling={applied !== query}
          onStep={step}
          onClose={close}
          inputRef={input}
          history={found ? { ...found, open: historyOpen, onToggle: () => setHistoryOpen(o => !o) } : undefined}
          seen={history?.kind === "messages" ? messages.result?.facets : undefined}
        />
      )}
      {showHistory && history.kind === "messages" && (
        <ChatSearchResults
          query={query}
          onQueryChange={setQuery}
          result={messages.result}
          failed={Boolean(messages.error)}
          needles={needles}
          onOpenHit={history.onOpenHit}
        />
      )}
      {showHistory && history.kind === "memories" && (
        <MemoryResults
          results={memories.data ?? null}
          failed={Boolean(memories.error)}
          needles={needles}
          onOpen={history.onOpen}
        />
      )}
      <div ref={content} className={cn("min-h-0 flex-1", contentClassName)}>
        {children}
      </div>
    </div>
  );
}

/** History over the room's memories: one line per memory the query is about. */
function MemoryResults({
  results,
  failed,
  needles,
  onOpen,
}: {
  results: MemorySearchResult[] | null;
  failed: boolean;
  needles: readonly string[];
  onOpen: (key: string) => void;
}) {
  if (failed && !results) {
    return (
      <Panel label="Search the room's memories">
        <p className="px-4 py-2 text-micro text-red">Hub unreachable: only this memory was searched.</p>
      </Panel>
    );
  }
  if (!results) return null;
  return (
    <Panel label="Search the room's memories">
      {results.length === 0 ? (
        <p className="px-4 py-2 text-micro text-muted-foreground">No memories match</p>
      ) : (
        <ul aria-label="Matching memories">
          {results.map(({ memory }) => (
            <li key={memory.key}>
              <button
                type="button"
                onClick={() => onOpen(memory.key)}
                className="flex w-full items-baseline gap-2 px-4 py-1 text-left text-label transition-colors hover:bg-hairline"
              >
                <span className="min-w-0 truncate text-text">
                  <HighlightText text={memoryTitle(memory)} highlight={{ query: needles }} />
                </span>
                {/* The title gets the width; the key gives way first. */}
                <span className="ml-auto min-w-0 max-w-[40%] truncate font-mono text-micro text-faint">{memory.key}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
