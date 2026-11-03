// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * Earlier agent sessions to bring into a room, for someone who may have
 * hundreds. A find box looks through their titles, folders and branches.
 * Sessions are grouped by folder, newest folder first; the newest folder is
 * open and the rest fold to a line with their count, and every folder that
 * matches opens while finding. A folder shows its newest few, with the rest a
 * click away.
 *
 * A session is told apart by its own words, its title, which only the
 * desktop app reads, on the machine the session is on. Listed from anywhere
 * else it has none, and the picker says where to see them.
 */

import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight, GitBranch, Laptop, MessageSquare, Search } from "lucide-react";
import type { AgentSessionSummary, Framework, Runner } from "@/lib/api";
import { Ago } from "@/lib/relative-time";
import { runnerName } from "@/lib/runners";
import { tildePath } from "@/components/launch-agent-dialog";
import { cn } from "@/lib/utils";

/** An earlier session a person could bring in, its agent CLI and its machine. */
export interface EarlierSession {
  runner: Runner;
  framework: Framework;
  session: AgentSessionSummary;
}

export const sessionKey = (s: EarlierSession) => `past:${s.runner.id}:${s.framework.id}:${s.session.id}`;

/** How many of a folder's sessions show before "Show more". */
const PER_FOLDER = 5;

function matches(s: EarlierSession, words: string[]): boolean {
  const text = `${s.session.title ?? ""} ${s.session.folder} ${s.session.branch ?? ""} ${s.framework.name}`.toLowerCase();
  return words.every((w) => text.includes(w));
}

export function EarlierSessions({
  sessions,
  picked,
  onPick,
}: {
  /** Newest first. */
  sessions: EarlierSession[];
  picked: string | null;
  onPick: (key: string) => void;
}) {
  const [typed, setTyped] = useState("");
  const words = typed.toLowerCase().split(/\s+/).filter(Boolean);
  const finding = words.length > 0;
  const [open, setOpen] = useState<Set<string> | null>(null);
  const [more, setMore] = useState<Set<string>>(new Set());

  const folders = useMemo(() => {
    const by = new Map<string, EarlierSession[]>();
    for (const s of sessions) if (matches(s, words)) by.set(s.session.folder, [...(by.get(s.session.folder) ?? []), s]);
    return [...by];
    // eslint-disable-next-line react-hooks/exhaustive-deps -- words is derived from typed
  }, [sessions, typed]);
  const shownCount = folders.reduce((n, [, list]) => n + list.length, 0);
  // Until someone folds or opens one, only the newest folder is open.
  const isOpen = (folder: string, i: number) => finding || (open ? open.has(folder) : i === 0);
  const toggle = (folder: string, i: number) =>
    setOpen((was) => {
      const next = new Set(was ?? (folders[0] ? [folders[0][0]] : []));
      if (isOpen(folder, i)) next.delete(folder);
      else next.add(folder);
      return next;
    });
  const titled = sessions.some((s) => s.session.title);
  const manyClis = new Set(sessions.map((s) => s.framework.id)).size > 1;
  const manyMachines = new Set(sessions.map((s) => s.runner.id)).size > 1;

  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-micro font-medium text-muted-foreground">Earlier sessions</p>
        <p className="text-micro text-faint tabular">
          {finding ? `${shownCount} of ${sessions.length}` : sessions.length}
        </p>
      </div>
      <label className="flex h-7 items-center gap-2 rounded-md border border-border bg-bg px-2 text-micro focus-within:border-border2">
        <Search className="size-3.5 flex-shrink-0 text-faint" aria-hidden />
        <input
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          placeholder="Find a session"
          aria-label="Find a session"
          spellCheck={false}
          className="min-w-0 flex-1 bg-transparent text-text outline-none placeholder:text-faint"
        />
      </label>
      {!titled && (
        <p className="text-micro text-faint">A session&apos;s title shows in the desktop app on the machine it&apos;s on.</p>
      )}
      {folders.length === 0 && <p className="py-1 text-micro text-faint">No session matches “{typed.trim()}”.</p>}
      <ul className="space-y-0.5">
        {folders.map(([folder, list], i) => {
          const expanded = isOpen(folder, i);
          const all = finding || more.has(folder);
          const shown = all ? list : list.slice(0, PER_FOLDER);
          return (
            <li key={folder}>
              <button
                type="button"
                onClick={() => toggle(folder, i)}
                aria-expanded={expanded}
                className="flex h-7 w-full items-center gap-1.5 rounded px-1 text-left text-micro hover:bg-hairline"
              >
                {expanded ? (
                  <ChevronDown className="size-3 flex-shrink-0 text-faint" />
                ) : (
                  <ChevronRight className="size-3 flex-shrink-0 text-faint" />
                )}
                <span className="min-w-0 flex-1 truncate font-mono text-muted-foreground">{tildePath(folder)}</span>
                <span className="flex-shrink-0 text-faint tabular">{list.length}</span>
                <span className="w-16 flex-shrink-0 text-right text-faint">
                  <Ago at={list[0].session.last_used} />
                </span>
              </button>
              {expanded && (
                <div className="space-y-1 pt-0.5 pb-1.5 pl-5">
                  {shown.map((s) => {
                    const k = sessionKey(s);
                    const active = picked === k;
                    return (
                      <button
                        key={k}
                        type="button"
                        role="radio"
                        aria-checked={active}
                        aria-label={s.session.title ?? `${s.framework.name} session in ${tildePath(folder)}`}
                        onClick={() => onPick(k)}
                        className={cn(
                          "block w-full rounded-md border px-2.5 py-1.5 text-left transition-colors",
                          active ? "border-accent bg-accent/10" : "border-transparent hover:border-border hover:bg-hairline",
                        )}
                      >
                        <span className="flex items-baseline gap-2">
                          <span className={cn("min-w-0 flex-1 truncate text-label", active ? "text-text" : "text-text/90")}>
                            {s.session.title ?? "Untitled session"}
                          </span>
                          <span className="flex-shrink-0 text-micro text-faint">
                            <Ago at={s.session.last_used} />
                          </span>
                        </span>
                        {/* What tells two apart, each with its own mark rather than a
                            string of dots: the branch, the length, and the CLI and
                            machine only when there's more than one of either. */}
                        <span className="flex min-w-0 items-center gap-3 text-micro text-faint">
                          {manyClis && <span className="flex-shrink-0">{s.framework.name}</span>}
                          {s.session.branch && (
                            <span className="flex min-w-0 items-center gap-1">
                              <GitBranch className="size-3 flex-shrink-0" aria-hidden />
                              <span className="truncate">{s.session.branch}</span>
                            </span>
                          )}
                          {s.session.messages ? (
                            <span className="flex flex-shrink-0 items-center gap-1" title={`${s.session.messages} messages`}>
                              <MessageSquare className="size-3" aria-hidden />
                              {s.session.messages}
                            </span>
                          ) : null}
                          {manyMachines && (
                            <span className="flex flex-shrink-0 items-center gap-1">
                              <Laptop className="size-3" aria-hidden />
                              {runnerName(s.runner)}
                            </span>
                          )}
                        </span>
                      </button>
                    );
                  })}
                  {!all && list.length > PER_FOLDER && (
                    <button
                      type="button"
                      onClick={() => setMore((m) => new Set(m).add(folder))}
                      className="rounded px-2.5 py-0.5 text-micro text-muted-foreground hover:bg-hairline hover:text-text"
                    >
                      Show {list.length - PER_FOLDER} more
                    </button>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
