// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Activity, Boxes, Brain, MessagesSquare, Users, type LucideIcon } from "lucide-react";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  EMPTY_SCOPE,
  TYPE_LABELS,
  hasScope,
  scopeChips,
  type SearchHit,
  type SearchResponse,
  type SearchResultType,
  type SearchScope,
} from "@/lib/search";
import { eventToChord, matchBinding } from "@/lib/keymap";

const ICONS: Record<SearchResultType, LucideIcon> = {
  room: Boxes,
  agent: Users,
  episode: Activity,
  memory: Brain,
  message: MessagesSquare,
};

/** Long enough that a fast typist issues one request per word rather than one
 *  per keystroke, short enough that the list still feels like typeahead. */
export const DEBOUNCE_MS = 140;

interface Props {
  open: boolean;
  /** Dismissal — Escape, the backdrop, or the chord again. Picking a result
   *  closes through `onPick` instead, so the two are told apart. */
  onClose: () => void;
  onPick: (hit: SearchHit) => void;
  /** Runs the query. Injected so the surface is testable without a backend and
   *  so it never has to know how the request is made. */
  search: (query: string, limit?: number) => Promise<SearchResponse>;
  mac: boolean;
}

/** Command-style search over everything in the hub.
 *
 *  One input, and the scope lives in the query: `#room` narrows to a room,
 *  `@handle` to an actor, `memory:` / `episode:` to a type, `kind:` to an L9
 *  kind. Those tokens are parsed by the backend and echoed back, so the chips
 *  under the input show the scope the results actually came from.
 *
 *  cmdk supplies the keyboard mechanics only. Its fuzzy filter is off: the
 *  backend has already ranked memories, episodes, messages, rooms and members
 *  against one another, and a second client-side sort over the words that
 *  happen to be in a row would undo exactly that work. So the list stays in
 *  server order, and each row says which kind of thing it is. */
export function SearchPalette({ open, onClose, onPick, search, mac }: Props) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchHit[]>([]);
  const [scope, setScope] = useState<SearchScope>(EMPTY_SCOPE);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const restoreTo = useRef<HTMLElement | null>(null);
  const picked = useRef(false);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setResults([]);
    setScope(EMPTY_SCOPE);
    setError(null);
    picked.current = false;
    restoreTo.current = document.activeElement as HTMLElement | null;

    // The app's keys are inert behind an open dialog, so this handles its own
    // dismissal — including the chord that opened it, as a toggle.
    const onKey = (e: KeyboardEvent) => {
      const closing =
        e.key === "Escape" || matchBinding(eventToChord(e, mac), ["global"])?.id === "search.open";
      if (!closing) return;
      e.preventDefault();
      onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      if (!picked.current) restoreTo.current?.focus?.();
    };
  }, [open, onClose, mac]);

  // Debounced, latest-wins. Responses can land out of order, so a stale one is
  // dropped by sequence rather than shown and then corrected.
  const sequence = useRef(0);
  useEffect(() => {
    if (!open) return;
    const trimmed = query.trim();
    if (!trimmed) {
      setResults([]);
      setScope(EMPTY_SCOPE);
      setPending(false);
      setError(null);
      return;
    }
    const mine = ++sequence.current;
    setPending(true);
    const timer = setTimeout(() => {
      search(trimmed)
        .then(response => {
          if (mine !== sequence.current) return;
          setResults(response.results);
          setScope(response.scope);
          setError(null);
        })
        .catch(err => {
          if (mine !== sequence.current) return;
          setResults([]);
          setError(err instanceof Error ? err.message : "Search failed");
        })
        .finally(() => {
          if (mine === sequence.current) setPending(false);
        });
    }, DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [open, query, search]);

  const chips = useMemo(() => scopeChips(scope), [scope]);
  const searching = query.trim() !== "";

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center p-6 pt-[12vh]">
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-[1px] motion-safe:animate-in motion-safe:fade-in-0"
        onClick={onClose}
        aria-hidden
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Search"
        className="relative flex w-full max-w-xl flex-col overflow-hidden rounded-xl border border-border bg-elevated shadow-2xl motion-safe:animate-in motion-safe:fade-in-0 motion-safe:zoom-in-95"
      >
        {/* shouldFilter={false}: the server ranked these across types already. */}
        <Command label="Search" loop shouldFilter={false}>
          <CommandInput
            autoFocus
            value={query}
            onValueChange={setQuery}
            placeholder="Search memories, episodes, messages…"
          />

          {hasScope(scope) && (
            <div className="flex flex-shrink-0 flex-wrap items-center gap-1.5 border-b border-border px-4 py-2">
              {chips.map(chip => (
                <span
                  key={chip}
                  className="rounded-full border border-border bg-surface px-2 py-0.5 font-mono text-micro text-accent"
                >
                  {chip}
                </span>
              ))}
            </div>
          )}

          <CommandList>
            {error ? (
              <p role="alert" className="py-8 text-center text-label text-red">
                {error}
              </p>
            ) : (
              <CommandEmpty>
                {!searching
                  ? "Type to search. #room, @agent, memory: and kind: narrow it."
                  : pending
                    ? "Searching…"
                    : "Nothing matched."}
              </CommandEmpty>
            )}

            {results.length > 0 && (
              <CommandGroup>
                {results.map(hit => {
                  const Icon = ICONS[hit.type];
                  return (
                    <CommandItem
                      key={`${hit.type}:${hit.room}:${hit.id}`}
                      value={`${hit.type}:${hit.room}:${hit.id}`}
                      onSelect={() => {
                        picked.current = true;
                        onPick(hit);
                      }}
                    >
                      <Icon className="text-faint" />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-text">{hit.title}</span>
                        {(hit.subtitle || hit.snippet) && (
                          <span className="block truncate text-micro text-muted-foreground">
                            {[hit.subtitle, hit.snippet].filter(Boolean).join(" — ")}
                          </span>
                        )}
                      </span>
                      <span className="ml-auto flex-shrink-0 text-micro text-faint">
                        {TYPE_LABELS[hit.type]}
                      </span>
                    </CommandItem>
                  );
                })}
              </CommandGroup>
            )}
          </CommandList>
        </Command>

        <footer className="flex flex-shrink-0 items-center gap-3 border-t border-border px-4 py-2 text-micro text-muted-foreground">
          <span>
            <kbd className="font-sans">↑↓</kbd> navigate
          </span>
          <span>
            <kbd className="font-sans">↵</kbd> open
          </span>
          <span>
            <kbd className="font-sans">esc</kbd> close
          </span>
          {pending && <span className="ml-auto">searching…</span>}
        </footer>
      </div>
    </div>
  );
}
