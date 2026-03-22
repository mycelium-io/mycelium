"use client";

import { useEffect, useState, useCallback } from "react";
import { fetchMemories, searchMemories, fetchCatchup } from "@/lib/api";

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
  latest_synthesis: { key: string; content: string | Record<string, unknown>; created_at: string } | null;
  recent_activity: { key: string; created_by: string; content_text: string; created_at: string }[];
  memories_since_synthesis: number;
}

interface Props {
  roomName: string;
  refreshTrigger: number;
}

export function MemoryPanel({ roomName, refreshTrigger }: Props) {
  const [memories, setMemories] = useState<Memory[]>([]);
  const [catchup, setCatchup] = useState<CatchupData | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [tab, setTab] = useState<"memories" | "synthesis">("memories");

  const loadData = useCallback(async () => {
    try {
      const [mems, cu] = await Promise.all([
        fetchMemories(roomName),
        fetchCatchup(roomName),
      ]);
      setMemories(mems);
      setCatchup(cu);
    } catch {}
  }, [roomName]);

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

  const synthContent = catchup?.latest_synthesis?.content;
  const synthText = typeof synthContent === "string"
    ? synthContent
    : typeof synthContent === "object" && synthContent
      ? (synthContent as Record<string, unknown>).synthesis as string || JSON.stringify(synthContent)
      : null;

  return (
    <div className="flex flex-col h-full">
      {/* Room info header */}
      <div className="px-4 py-3 border-b border-border">
        <div className="flex items-center gap-3 text-sm">
          <span className="font-bold">{catchup?.total_memories || 0}</span>
          <span className="text-muted">memories</span>
          <span className="text-muted/30">|</span>
          <span className="font-bold">{catchup?.contributors?.length || 0}</span>
          <span className="text-muted">contributors</span>
        </div>
        {catchup?.contributors && catchup.contributors.length > 0 && (
          <div className="flex gap-1.5 mt-2 flex-wrap">
            {catchup.contributors.map(c => (
              <span key={c} className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-accent/5 text-accent/70 border border-accent/10">
                {c}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Tabs */}
      <div className="flex border-b border-border">
        <button
          onClick={() => setTab("memories")}
          className={`flex-1 py-2 text-xs font-bold uppercase tracking-wider transition-colors ${
            tab === "memories" ? "text-accent border-b-2 border-accent" : "text-muted hover:text-white"
          }`}
        >
          Memories
        </button>
        <button
          onClick={() => setTab("synthesis")}
          className={`flex-1 py-2 text-xs font-bold uppercase tracking-wider transition-colors ${
            tab === "synthesis" ? "text-emerald-400 border-b-2 border-emerald-400" : "text-muted hover:text-white"
          }`}
        >
          Synthesis
        </button>
      </div>

      {tab === "memories" && (
        <div className="flex-1 overflow-y-auto">
          {/* Search */}
          <div className="px-4 py-3 border-b border-border">
            <div className="flex gap-2">
              <input
                className="flex-1 bg-bg border border-border rounded-lg px-3 py-1.5 text-sm font-mono focus:border-accent/50 focus:outline-none"
                placeholder="semantic search..."
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                onKeyDown={e => e.key === "Enter" && handleSearch()}
              />
              <button
                onClick={handleSearch}
                disabled={searching}
                className="px-3 py-1.5 bg-accent/10 text-accent border border-accent/20 rounded-lg text-sm font-bold hover:bg-accent/20 transition-all disabled:opacity-50"
              >
                {searching ? "..." : "Search"}
              </button>
            </div>
          </div>

          {/* Search results */}
          {searchResults && (
            <div className="px-4 py-2 border-b border-border bg-accent/[0.02]">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs text-muted font-bold uppercase tracking-wider">
                  {searchResults.length} result{searchResults.length !== 1 ? "s" : ""}
                </span>
                <button onClick={() => setSearchResults(null)} className="text-xs text-muted hover:text-white">
                  clear
                </button>
              </div>
              {searchResults.map((r, i) => (
                <div key={i} className="py-2 border-t border-border/50 first:border-t-0">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-sm text-accent">{r.memory.key}</span>
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-yellow-500/10 text-yellow-400 font-bold">
                      {(r.similarity * 100).toFixed(0)}%
                    </span>
                  </div>
                  <p className="text-xs text-muted mt-1 line-clamp-2">{formatValue(r.memory.value)}</p>
                </div>
              ))}
            </div>
          )}

          {/* Memory list */}
          <div className="px-4 py-2 space-y-1">
            {memories.map(mem => (
              <div key={mem.key} className="py-2.5 border-b border-border/30 last:border-b-0">
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-mono text-sm text-accent">{mem.key}</span>
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-surface text-muted border border-border font-bold">
                    v{mem.version}
                  </span>
                  <span className="ml-auto text-[10px] text-muted/40">{mem.created_by}</span>
                </div>
                <p className="text-xs text-muted line-clamp-2 font-mono">
                  {formatValue(mem.value)}
                </p>
                {mem.file_path && (
                  <p className="text-[10px] text-muted/30 mt-1 font-mono">{mem.file_path}</p>
                )}
              </div>
            ))}
            {memories.length === 0 && (
              <div className="text-center text-muted/50 py-10 text-sm">No memories yet</div>
            )}
          </div>
        </div>
      )}

      {tab === "synthesis" && (
        <div className="flex-1 overflow-y-auto px-4 py-4">
          {synthText ? (
            <>
              <div className="text-xs text-muted font-mono mb-3">
                {catchup?.latest_synthesis?.key} — {catchup?.latest_synthesis?.created_at?.slice(0, 16)}
              </div>
              <div className="prose prose-invert prose-sm max-w-none text-sm text-[#c0cce0] leading-relaxed whitespace-pre-wrap">
                {synthText}
              </div>
            </>
          ) : (
            <div className="text-center text-muted/50 py-10 text-sm">
              No synthesis yet.<br />
              <span className="text-xs">Run <code className="bg-surface px-1 rounded">mycelium synthesize</code></span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
