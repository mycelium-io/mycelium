// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useMemo, useState, useCallback } from "react";
import { fetchMemories, searchMemories } from "@/lib/api";

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

interface Props {
  roomName: string;
  masId?: string | null;
  refreshTrigger: number;
}

export function MemoryPanel({ roomName, refreshTrigger }: Props) {
  const [memories, setMemories] = useState<Memory[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[] | null>(null);
  const [searching, setSearching] = useState(false);

  const loadData = useCallback(async () => {
    try {
      const mems = await fetchMemories(roomName);
      setMemories(mems);
    } catch {}
  }, [roomName]);

  const contributors = useMemo(
    () => Array.from(new Set(memories.map(m => m.created_by).filter(Boolean))),
    [memories],
  );

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

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Stats row */}
      <div className="px-4 py-3 border-b border-border bg-paper">
        <div className="flex items-baseline gap-3 caps-mono-sm text-muted">
          <span className="text-text font-semibold tabular">{memories.length}</span>
          <span>memories</span>
          <span className="text-dim">·</span>
          <span className="text-text font-semibold tabular">{contributors.length}</span>
          <span>contributors</span>
        </div>
        {contributors.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-2">
            {contributors.map(c => (
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
    </div>
  );
}
