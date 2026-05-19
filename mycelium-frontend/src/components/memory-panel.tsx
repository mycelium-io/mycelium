// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

"use client";

import { useEffect, useState, useCallback } from "react";
import {
  fetchMemories,
  searchMemories,
  fetchCatchup,
  fetchPlan,
  togglePlanTask,
  addPlanTask,
  type PlanResponse,
} from "@/lib/api";
import { KnowledgePanel } from "./knowledge-panel";
import { MarkdownContent } from "./markdown-content";

interface Memory {
  key: string;
  value: unknown;
  content_text?: string;
  version: number;
  created_by: string;
  updated_at: string;
  file_path?: string;
}

interface SearchResult {
  memory: Memory;
  similarity: number;
}

interface CatchupData {
  room: string;
  mode: string;
  total_memories: number;
  contributors: string[];
  latest_synthesis: { key: string; content: string; created_at: string } | null;
  recent_activity: { key: string; created_by: string; content_text: string; created_at: string }[];
  memories_since_synthesis: number;
}

interface Props {
  roomName: string;
  masId?: string | null;
  refreshTrigger: number;
}

type Tab = "memories" | "plan" | "synthesis" | "knowledge";

const TABS: { id: Tab; label: string }[] = [
  { id: "memories",  label: "MEMORIES" },
  { id: "plan",      label: "PLAN" },
  { id: "synthesis", label: "SYNTHESIS" },
  { id: "knowledge", label: "KNOWLEDGE" },
];

export function MemoryPanel({ roomName, masId, refreshTrigger }: Props) {
  const [memories, setMemories] = useState<Memory[]>([]);
  const [catchup, setCatchup] = useState<CatchupData | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [tab, setTab] = useState<Tab>("memories");
  const [plan, setPlan] = useState<PlanResponse | null>(null);
  const [newTaskText, setNewTaskText] = useState("");

  const loadData = useCallback(async () => {
    try {
      const [mems, cu, pl] = await Promise.all([
        fetchMemories(roomName),
        fetchCatchup(roomName),
        fetchPlan(roomName),
      ]);
      setMemories(mems);
      setCatchup(cu);
      setPlan(pl);
    } catch {}
  }, [roomName]);

  const refreshPlan = useCallback(async () => {
    try {
      setPlan(await fetchPlan(roomName));
    } catch {}
  }, [roomName]);

  const onToggleTask = async (taskId: string, done: boolean) => {
    await togglePlanTask(roomName, taskId, done);
    await refreshPlan();
  };

  const onAddTask = async () => {
    const text = newTaskText.trim();
    if (!text) return;
    setNewTaskText("");
    await addPlanTask(roomName, text);
    await refreshPlan();
  };

  useEffect(() => { loadData(); }, [loadData, refreshTrigger]);

  const handleSearch = async () => {
    if (!searchQuery.trim()) { setSearchResults(null); return; }
    setSearching(true);
    try {
      const data = await searchMemories(roomName, searchQuery);
      setSearchResults(data.results || []);
    } finally {
      setSearching(false);
    }
  };

  const formatValue = (v: unknown): string => {
    if (typeof v === "string") return v;
    if (typeof v === "object" && v !== null) {
      const obj = v as Record<string, unknown>;
      if ("text" in obj) return obj.text as string;
      return JSON.stringify(v, null, 0);
    }
    return String(v);
  };

  const synthText = catchup?.latest_synthesis?.content ?? null;

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Stats row */}
      <div className="px-4 py-3 border-b border-border bg-paper">
        <div className="flex items-baseline gap-3 caps-mono-sm text-muted">
          <span className="text-text font-semibold tabular">{catchup?.total_memories ?? 0}</span>
          <span>memories</span>
          <span className="text-dim">·</span>
          <span className="text-text font-semibold tabular">{catchup?.contributors?.length ?? 0}</span>
          <span>contributors</span>
        </div>
        {catchup?.contributors && catchup.contributors.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-2">
            {catchup.contributors.map(c => (
              <span
                key={c}
                className="font-mono text-micro px-2 py-0.5 text-text2 border border-border"
                style={{ background: "rgba(255,255,255,0.02)" }}
              >
                {c}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Tabs */}
      <div className="flex items-stretch border-b border-border bg-paper">
        {TABS.map(t => {
          const active = tab === t.id;
          return (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`flex-1 py-2 caps-mono-sm transition-colors ${
                active ? "text-accent" : "text-text2 hover:text-text"
              }`}
              style={{ borderBottom: `2px solid ${active ? "var(--accent)" : "transparent"}` }}
            >
              {t.label}
            </button>
          );
        })}
      </div>

      {tab === "memories" && (
        <div className="flex-1 overflow-y-auto">
          {/* Search */}
          <div className="px-4 py-3 border-b border-border bg-paper">
            <div className="flex gap-2">
              <input
                className="flex-1 bg-bg border border-border px-3 py-1.5 text-label font-mono text-text placeholder:text-muted focus:border-accent focus:outline-none transition-colors"
                placeholder="semantic search…"
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                onKeyDown={e => e.key === "Enter" && handleSearch()}
              />
              <button
                onClick={handleSearch}
                disabled={searching}
                className="flex items-center gap-2 px-3 py-1.5 caps-mono-sm border border-accent/40 bg-accent/[0.06] text-accent transition-colors hover:bg-accent/[0.12] hover:border-accent/60 disabled:opacity-50"
              >
                {searching ? "…" : "SEARCH"}
              </button>
            </div>
          </div>

          {/* Search results */}
          {searchResults && (
            <div className="border-b border-border" style={{ background: "rgba(93,212,224,0.03)" }}>
              <div className="flex items-center gap-2 px-4 py-2 border-b border-border">
                <span className="caps-mono-sm text-muted">
                  <span className="text-text font-semibold tabular">{searchResults.length}</span> RESULTS
                </span>
                <button
                  onClick={() => setSearchResults(null)}
                  className="ml-auto caps-mono-sm text-text2 hover:text-accent transition-colors"
                >
                  CLEAR
                </button>
              </div>
              {searchResults.map((r, i) => (
                <div key={i} className="px-4 py-2 border-b border-border last:border-b-0">
                  <div className="flex items-baseline gap-2 mb-1">
                    <span className="font-mono text-label text-accent truncate">{r.memory.key}</span>
                    <span className="caps-mono-sm tabular ml-auto" style={{ color: "var(--yellow)" }}>
                      {(r.similarity * 100).toFixed(0)}%
                    </span>
                  </div>
                  <p className="text-label text-text2 line-clamp-2">{formatValue(r.memory.value)}</p>
                </div>
              ))}
            </div>
          )}

          {/* Memory list */}
          <div>
            {memories.map(mem => (
              <div key={mem.key} className="px-4 py-2.5 border-b border-border last:border-b-0">
                <div className="flex items-baseline gap-2 mb-1">
                  <span className="font-mono text-label text-accent truncate min-w-0">{mem.key}</span>
                  <span className="caps-mono-sm text-muted tabular flex-shrink-0">v{mem.version}</span>
                  <span className="ml-auto caps-mono-sm text-muted truncate flex-shrink-0">{mem.created_by}</span>
                </div>
                <p className="text-label text-text2 line-clamp-2 font-mono leading-snug">
                  {formatValue(mem.value)}
                </p>
              </div>
            ))}
            {memories.length === 0 && (
              <div className="text-center caps-mono-sm text-muted italic py-10">
                no memories yet
              </div>
            )}
          </div>
        </div>
      )}

      {tab === "plan" && (
        <div className="flex-1 overflow-y-auto">
          {/* Add-task row */}
          <div className="px-4 py-3 border-b border-border bg-paper">
            <div className="flex gap-2">
              <input
                className="flex-1 bg-bg border border-border px-3 py-1.5 text-label font-mono text-text placeholder:text-muted focus:border-accent focus:outline-none transition-colors"
                placeholder="add a task…"
                value={newTaskText}
                onChange={e => setNewTaskText(e.target.value)}
                onKeyDown={e => e.key === "Enter" && onAddTask()}
              />
              <button
                onClick={onAddTask}
                disabled={!newTaskText.trim()}
                className="flex items-center gap-2 px-3 py-1.5 caps-mono-sm border border-accent/40 bg-accent/[0.06] text-accent transition-colors hover:bg-accent/[0.12] hover:border-accent/60 disabled:opacity-50"
              >
                ADD
              </button>
            </div>
            <div className="flex items-baseline gap-3 caps-mono-sm text-muted mt-3">
              <span className="text-text font-semibold tabular">{plan?.open_count ?? 0}</span>
              <span>open</span>
              <span className="text-dim">·</span>
              <span className="text-text font-semibold tabular">{plan?.done_count ?? 0}</span>
              <span>done</span>
              <span className="text-dim">·</span>
              <span className="text-text font-semibold tabular">{plan?.files.length ?? 0}</span>
              <span>files</span>
            </div>
          </div>

          {/* Per-file task groups */}
          <div>
            {plan?.files.map(f => (
              <div key={f.slug} className="border-b border-border last:border-b-0">
                <div className="px-4 py-2 bg-paper/40 border-b border-border flex items-baseline gap-2">
                  <span className="font-mono text-label text-accent truncate">{f.slug}</span>
                  <span className="caps-mono-sm text-muted">{f.title}</span>
                  <span className="ml-auto caps-mono-sm text-muted tabular">
                    {f.tasks.filter(t => !t.done).length}/{f.tasks.length}
                  </span>
                </div>
                {f.tasks.length === 0 ? (
                  <div className="px-4 py-2 caps-mono-sm text-muted italic">no tasks in this file</div>
                ) : (
                  f.tasks.map(t => (
                    <label
                      key={t.id}
                      className="flex items-start gap-3 px-4 py-2 border-t border-border/50 cursor-pointer hover:bg-paper/30"
                    >
                      <input
                        type="checkbox"
                        checked={t.done}
                        onChange={e => onToggleTask(t.id, e.target.checked)}
                        className="mt-1 accent-accent"
                      />
                      <span
                        className={
                          "text-label font-mono " +
                          (t.done ? "line-through text-muted" : "text-text")
                        }
                      >
                        {t.text}
                      </span>
                    </label>
                  ))
                )}
              </div>
            ))}
            {(!plan || plan.files.length === 0) && (
              <div className="text-center caps-mono-sm text-muted italic py-10">
                no plan yet — add a task above
              </div>
            )}
          </div>
        </div>
      )}

      {tab === "synthesis" && (
        <div className="flex-1 overflow-y-auto px-4 py-4">
          {synthText ? (
            <>
              <div className="caps-mono-sm text-muted mb-3 truncate">
                {catchup?.latest_synthesis?.key} · {catchup?.latest_synthesis?.created_at?.slice(0, 16)}
              </div>
              <MarkdownContent>{synthText}</MarkdownContent>
            </>
          ) : (
            <div className="text-center caps-mono-sm text-muted italic py-10">
              no synthesis yet
              <div className="font-mono text-label text-text2 mt-3 normal-case tracking-normal not-italic">
                run <code className="bg-surface px-1.5 py-0.5 text-accent border border-border">mycelium synthesize</code>
              </div>
            </div>
          )}
        </div>
      )}

      {tab === "knowledge" && (
        <div className="flex-1 overflow-hidden">
          <KnowledgePanel masId={masId} />
        </div>
      )}
    </div>
  );
}
