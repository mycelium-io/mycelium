// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useMemo, useState, useCallback } from "react";
import { Brain } from "lucide-react";
import { fetchMemories, searchMemories } from "@/lib/api";
import { DetailDrawer } from "@/components/detail-drawer";
import { EmptyState } from "@/components/empty-state";
import { MemoryDetail } from "@/components/memory-detail";

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
  const [selected, setSelected] = useState<Memory | null>(null);

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
        <div className="flex items-baseline gap-1.5 text-label text-muted-foreground">
          <span className="text-text font-semibold tabular">{memories.length}</span>
          <span>memories</span>
          <span className="text-faint px-1">·</span>
          <span className="text-text font-semibold tabular">{contributors.length}</span>
          <span>contributors</span>
        </div>
        {contributors.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-2.5">
            {contributors.map(c => (
              <span
                key={c}
                className="font-mono text-micro rounded-full px-2 py-0.5 text-muted-foreground bg-surface border border-border"
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
              className="flex-1 rounded-lg bg-surface border border-border px-3 py-2 text-label text-text placeholder:text-muted-foreground focus:border-accent focus:bg-bg focus:outline-none transition-colors"
              placeholder="Search memory…"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              onKeyDown={e => e.key === "Enter" && handleSearch()}
            />
            <button
              onClick={handleSearch}
              disabled={searching}
              className="rounded-lg px-3.5 py-2 text-label font-medium bg-accent text-accent-fg transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {searching ? "…" : "Search"}
            </button>
          </div>
        </div>

        {/* Search results */}
        {searchResults && (
          <div className="border-b border-border bg-accent-soft">
            <div className="flex items-center gap-2 px-4 py-2 border-b border-border">
              <span className="text-label text-muted-foreground">
                <span className="text-text font-semibold tabular">{searchResults.length}</span> results
              </span>
              <button
                onClick={() => setSearchResults(null)}
                className="ml-auto text-label text-muted-foreground hover:text-accent transition-colors"
              >
                Clear
              </button>
            </div>
            {searchResults.map((r, i) => (
              <button
                key={i}
                onClick={() => setSelected(r.memory)}
                className="block w-full text-left px-4 py-2.5 border-b border-border last:border-b-0 transition-colors hover:bg-hairline"
              >
                <div className="flex items-baseline gap-2 mb-1">
                  <span className="font-mono text-label text-accent truncate">{r.memory.key}</span>
                  <span className="text-micro tabular ml-auto text-muted-foreground">
                    {(r.similarity * 100).toFixed(0)}% match
                  </span>
                </div>
                <p className="text-label text-muted-foreground line-clamp-2 leading-snug">{formatValue(r.memory.value)}</p>
              </button>
            ))}
          </div>
        )}

        {/* Memory list */}
        <div>
          {memories.map(mem => (
            <button
              key={mem.key}
              onClick={() => setSelected(mem)}
              className="block w-full text-left px-4 py-3 border-b border-border last:border-b-0 transition-colors hover:bg-hairline"
            >
              <div className="flex items-baseline gap-2 mb-1">
                <span className="font-mono text-label text-accent truncate min-w-0">{mem.key}</span>
                <span className="font-mono text-micro text-muted-foreground tabular flex-shrink-0">v{mem.version}</span>
                <span className="ml-auto text-micro text-muted-foreground truncate flex-shrink-0">{mem.created_by}</span>
              </div>
              <p className="text-label text-muted-foreground line-clamp-2 leading-snug">
                {formatValue(mem.value)}
              </p>
            </button>
          ))}
          {memories.length === 0 && (
            <EmptyState
              size="sm"
              icon={Brain}
              title="No memories yet"
              description="Decisions, context, and status land here as the room works."
            />
          )}
        </div>
      </div>

      <DetailDrawer
        open={selected !== null}
        onClose={() => setSelected(null)}
        title={selected?.key}
        subtitle={selected ? `v${selected.version} · ${selected.created_by}` : undefined}
      >
        {selected && <MemoryDetail memory={selected} />}
      </DetailDrawer>
    </div>
  );
}
