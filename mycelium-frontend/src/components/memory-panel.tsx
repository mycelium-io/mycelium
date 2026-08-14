// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useMemo, useState, useCallback } from "react";
import { Brain, ChevronRight } from "lucide-react";
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

interface TreeNode {
  name: string;
  path: string;
  memory?: Memory;
  children: TreeNode[];
}

interface Props {
  roomName: string;
  masId?: string | null;
  refreshTrigger: number;
}

function buildTree(memories: Memory[]): TreeNode[] {
  const root: TreeNode = { name: "", path: "", children: [] };

  for (const mem of memories) {
    const parts = mem.key.split("/");
    let node = root;
    for (let i = 0; i < parts.length; i++) {
      const part = parts[i];
      const path = parts.slice(0, i + 1).join("/");
      let child = node.children.find(c => c.name === part);
      if (!child) {
        child = { name: part, path, children: [] };
        node.children.push(child);
      }
      if (i === parts.length - 1) child.memory = mem;
      node = child;
    }
  }

  const sort = (nodes: TreeNode[]) => {
    nodes.sort((a, b) => {
      // folders before leaves, then alphabetically
      const aFolder = a.children.length > 0;
      const bFolder = b.children.length > 0;
      if (aFolder !== bFolder) return aFolder ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
    for (const n of nodes) sort(n.children);
  };
  sort(root.children);

  return root.children;
}

function formatValue(v: unknown): string {
  if (typeof v === "string") return v;
  if (typeof v === "object" && v !== null) {
    const obj = v as Record<string, unknown>;
    if ("text" in obj) return obj.text as string;
    return JSON.stringify(v, null, 0);
  }
  return String(v);
}

interface TreeRowsProps {
  nodes: TreeNode[];
  depth: number;
  collapsed: Set<string>;
  onToggle: (path: string) => void;
  onSelect: (mem: Memory) => void;
}

function TreeRows({ nodes, depth, collapsed, onToggle, onSelect }: TreeRowsProps) {
  return (
    <>
      {nodes.map(node => {
        const isFolder = node.children.length > 0;
        const isCollapsed = collapsed.has(node.path);
        const indent = depth * 12 + 16;

        return (
          <div key={node.path}>
            {isFolder ? (
              <>
                <button
                  onClick={() => {
                    onToggle(node.path);
                    if (node.memory) onSelect(node.memory);
                  }}
                  className="flex w-full items-center gap-1 py-1.5 text-left text-label text-muted-foreground hover:text-text border-b border-border transition-colors select-none"
                  style={{ paddingLeft: indent }}
                >
                  <ChevronRight
                    size={12}
                    className={`flex-shrink-0 text-faint transition-transform ${isCollapsed ? "" : "rotate-90"}`}
                  />
                  <span className="font-mono">{node.name}/</span>
                  {node.memory && (
                    <span className="ml-1.5 text-micro text-faint font-mono">v{node.memory.version}</span>
                  )}
                  <span className="ml-auto pr-4 font-mono text-micro text-faint tabular">
                    {node.children.length}
                  </span>
                </button>
                {!isCollapsed && (
                  <TreeRows
                    nodes={node.children}
                    depth={depth + 1}
                    collapsed={collapsed}
                    onToggle={onToggle}
                    onSelect={onSelect}
                  />
                )}
              </>
            ) : (
              <button
                onClick={() => node.memory && onSelect(node.memory)}
                className="block w-full text-left py-2.5 border-b border-border last:border-b-0 transition-colors hover:bg-hairline"
                style={{ paddingLeft: indent + 16, paddingRight: 16 }}
              >
                <div className="flex items-baseline gap-2 mb-0.5">
                  <span className="font-mono text-label text-accent truncate min-w-0">{node.name}</span>
                  {node.memory && (
                    <>
                      <span className="font-mono text-micro text-muted-foreground tabular flex-shrink-0">
                        v{node.memory.version}
                      </span>
                      <span className="ml-auto text-micro text-muted-foreground truncate flex-shrink-0">
                        {node.memory.created_by}
                      </span>
                    </>
                  )}
                </div>
                {node.memory && (
                  <p className="text-label text-muted-foreground line-clamp-2 leading-snug">
                    {formatValue(node.memory.value)}
                  </p>
                )}
              </button>
            )}
          </div>
        );
      })}
    </>
  );
}

export function MemoryPanel({ roomName, refreshTrigger }: Props) {
  const [memories, setMemories] = useState<Memory[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [selected, setSelected] = useState<Memory | null>(null);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

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

  const tree = useMemo(() => buildTree(memories), [memories]);

  const toggleNs = useCallback((path: string) =>
    setCollapsed(prev => {
      const next = new Set(prev);
      next.has(path) ? next.delete(path) : next.add(path);
      return next;
    }), []);

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

        {/* Search results — flat list with similarity scores */}
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

        {/* File tree */}
        {!searchResults && (
          <div>
            {memories.length === 0 ? (
              <EmptyState
                size="sm"
                icon={Brain}
                title="No memories yet"
                description="Decisions, context, and status land here as the room works."
              />
            ) : (
              <TreeRows
                nodes={tree}
                depth={0}
                collapsed={collapsed}
                onToggle={toggleNs}
                onSelect={setSelected}
              />
            )}
          </div>
        )}
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
