// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Brain,
  ChevronRight,
  ExternalLink,
  Folder,
  FolderOpen,
  FileText,
  AlertCircle,
  Network,
} from "lucide-react";
import {
  fetchMemory,
  fetchMemoryExpanded,
  searchMemories,
  type Memory,
  type MemorySearchResult,
} from "@/lib/api";
import { useRoomMemories, useRoomMemoryIntegrity } from "@/lib/room-data";
import { memoryGraphHref, memoryHref } from "@/lib/memory-routes";
import { expandedPathsForKey, resolveMemoryPeekNavigation } from "@/lib/memory-panel-nav";
import { DetailDrawer } from "@/components/detail-drawer";
import { EmptyState } from "@/components/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { MemoryDetail } from "@/components/memory-detail";

interface TreeNode {
  name: string;
  path: string;
  memory?: Memory;
  children: TreeNode[];
}

interface Props {
  roomName: string;
  masId?: string | null;
  /** A memory key to open, arrived at from search. */
  focusKey?: string | null;
  onFocusConsumed?: () => void;
  /** Select and reveal a memory by key (e.g. a chat `[[wikilink]]` was clicked).
   *  The nonce lets the same key re-open after the reader has browsed elsewhere. */
  focusMemory?: { key: string; nonce: number } | null;
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

// Filename for a memory leaf, with its extension. Keys usually omit it (they're
// stored as markdown); a structured value with no `text` field is really JSON.
// A key that already carries an extension is shown as-is.
function fileName(node: TreeNode): string {
  if (node.name.includes(".")) return node.name;
  const v = node.memory?.value;
  const ext = v && typeof v === "object" && !("text" in (v as Record<string, unknown>)) ? "json" : "md";
  return `${node.name}.${ext}`;
}

const ROW_H = 22; // px, matches vscode compact density
const INDENT = 12; // px per depth level

interface TreeRowsProps {
  nodes: TreeNode[];
  depth: number;
  collapsed: Set<string>;
  onToggle: (path: string) => void;
  onSelect: (mem: Memory) => void;
  selected: Memory | null;
}

function TreeRows({ nodes, depth, collapsed, onToggle, onSelect, selected }: TreeRowsProps) {
  return (
    <>
      {nodes.map(node => {
        const isFolder = node.children.length > 0;
        const isOpen = isFolder && !collapsed.has(node.path);
        const isSelected = selected?.key === node.path;
        const paddingLeft = 8 + depth * INDENT;

        return (
          <div key={node.path}>
            <div
              style={{ paddingLeft, height: ROW_H }}
              className={`flex w-full items-center gap-1.5 pr-3 transition-colors
                ${isSelected ? "bg-accent/15 text-text" : "hover:bg-muted text-muted-foreground hover:text-text"}`}
            >
              {/* chevron — separate click target so it only toggles */}
              <button
                onClick={() => isFolder && onToggle(node.path)}
                className="flex-shrink-0 w-3 flex items-center justify-center"
                tabIndex={isFolder ? 0 : -1}
              >
                {isFolder && (
                  <ChevronRight
                    size={11}
                    className={`text-faint transition-transform ${isOpen ? "rotate-90" : ""}`}
                  />
                )}
              </button>

              {/* icon + name — clicking opens the memory (or toggles folder if no memory) */}
              <button
                onClick={() => node.memory ? onSelect(node.memory) : isFolder && onToggle(node.path)}
                className="flex items-center gap-1.5 min-w-0 flex-1 text-left"
              >
                <span className="flex-shrink-0">
                  {isFolder
                    ? isOpen
                      ? <FolderOpen size={14} className="text-accent" />
                      : <Folder size={14} className="text-accent opacity-70" />
                    : <FileText size={13} className="text-faint" />
                  }
                </span>

                <span className="font-mono text-[11.5px] leading-none truncate min-w-0">
                  {isFolder ? node.name : fileName(node)}
                </span>

                  {isFolder && node.memory && (
                  <span className="flex-shrink-0 w-1 h-1 rounded-full bg-accent opacity-60" />
                )}
              </button>

              {/* skill tag — a skill is just a skills/… memory, flagged here */}
              {node.memory && !isFolder && node.memory.key.startsWith("skills/") && (
                <span className="flex-shrink-0 rounded-sm border border-accent/30 bg-accent/10 px-1 text-[9px] font-medium leading-tight text-accent">
                  skill
                </span>
              )}

              {node.memory && !isFolder && (
                <span className="flex-shrink-0 font-mono text-[10px] tabular text-faint">
                  v{node.memory.version}
                </span>
              )}
            </div>

            {isOpen && (
              <TreeRows
                nodes={node.children}
                depth={depth + 1}
                collapsed={collapsed}
                onToggle={onToggle}
                onSelect={onSelect}
                selected={selected}
              />
            )}
          </div>
        );
      })}
    </>
  );
}

export function MemoryPanel({ roomName, focusKey = null, onFocusConsumed, focusMemory }: Props) {
  const router = useRouter();
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<MemorySearchResult[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Memory | null>(null);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [renderedBody, setRenderedBody] = useState<string | null>(null);

  // The tree, plus the room-wide integrity report the drawer reads to flag a
  // broken or orphaned memory without a per-open round trip. Both revalidate
  // when a memory write reaches the room, so neither needs a refresh prop.
  const { memories, loading } = useRoomMemories(roomName);
  const { integrity } = useRoomMemoryIntegrity(roomName);
  const memoriesRef = useRef(memories);
  memoriesRef.current = memories;

  // Expanded transclusions for whichever memory is open in the drawer, so the
  // rail peek matches the full page instead of leaving `![[…]]` markers as
  // unexpanded chips (#599).
  useEffect(() => {
    if (!selected) {
      setRenderedBody(null);
      return;
    }
    let live = true;
    setRenderedBody(null);
    fetchMemoryExpanded(roomName, selected.key).then(exp => {
      if (live && exp.found && exp.rendered) setRenderedBody(exp.rendered);
    });
    return () => {
      live = false;
    };
  }, [roomName, selected]);

  const contributors = useMemo(
    () => Array.from(new Set(memories.map(m => m.created_by).filter(Boolean))),
    [memories],
  );

  const revealKeyInTree = useCallback((key: string, clearSearch = false) => {
    if (clearSearch) setSearchResults(null);
    setCollapsed(prev => {
      const next = new Set(prev);
      for (const path of expandedPathsForKey(key)) next.delete(path);
      return next;
    });
  }, []);

  const openMemoryByKey = useCallback(
    async (key: string) => {
      const nav = await resolveMemoryPeekNavigation(
        roomName,
        key,
        memoriesRef.current,
        fetchMemory,
      );
      if (nav.action === "drawer") {
        setSelected(nav.memory);
        revealKeyInTree(key, true);
        return;
      }
      router.push(nav.href);
    },
    [roomName, revealKeyInTree, router],
  );

  // Arriving from search: open the named memory and reveal its folder. The tree
  // only holds the first page of keys, so the memory is fetched by key rather
  // than looked up in what happens to be loaded.
  useEffect(() => {
    if (!focusKey) return;
    // Consumed only once the memory is in hand: clearing the request first would
    // unmount the effect that is still fetching what it asked for.
    void openMemoryByKey(focusKey).finally(() => onFocusConsumed?.());
  }, [roomName, focusKey, onFocusConsumed, openMemoryByKey]);

  const handleSearch = async () => {
    if (!searchQuery.trim()) { setSearchResults(null); setSearchError(null); return; }
    setSearching(true);
    setSearchError(null);
    try {
      setSearchResults(await searchMemories(roomName, searchQuery));
    } catch (err) {
      setSearchError(err instanceof Error ? err.message : "Search failed");
      setSearchResults(null);
    } finally {
      setSearching(false);
    }
  };

  const tree = useMemo(() => buildTree(memories), [memories]);

  // A chat `[[wikilink]]` (or any external focus request) selects that memory.
  // The nonce re-fires the same key on a repeat click.
  useEffect(() => {
    if (focusMemory?.key) void openMemoryByKey(focusMemory.key);
  }, [focusMemory, openMemoryByKey]);

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
          <Link
            href={memoryGraphHref(roomName)}
            className="ml-auto inline-flex items-center gap-1 rounded-md px-2 py-1 text-micro font-medium text-accent transition-colors hover:bg-hairline"
            title="Open the memory link graph"
          >
            <Network className="size-3.5" />
            Graph
          </Link>
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
          {searchError && (
            <p role="alert" className="mt-2 flex items-center gap-1.5 text-micro text-red">
              <AlertCircle className="size-3.5 flex-shrink-0" />
              {searchError}
            </p>
          )}
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
                <p className="text-label text-muted-foreground line-clamp-2 leading-snug">
                  {formatValue(r.memory.value)}
                </p>
              </button>
            ))}
          </div>
        )}

        {/* File tree */}
        {!searchResults && (
          <div className="py-1">
            {loading ? (
              ["w-24", "w-32", "w-20", "w-28"].map((w, i) => (
                <div key={i} className="flex items-center gap-1.5 pr-3" style={{ height: ROW_H, paddingLeft: 8 }}>
                  <Skeleton className="size-3 rounded-sm" />
                  <Skeleton className={`h-2.5 ${w}`} />
                </div>
              ))
            ) : memories.length === 0 ? (
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
                selected={selected}
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
        actions={
          selected ? (
            <Link
              href={memoryHref(roomName, selected.key)}
              className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-micro font-medium text-accent transition-colors hover:bg-hairline"
              title="Open full page"
            >
              <ExternalLink className="size-3.5" />
              Full page
            </Link>
          ) : undefined
        }
      >
        {selected && (
          <MemoryDetail
            memory={selected}
            roomName={roomName}
            onNavigate={openMemoryByKey}
            renderedBody={renderedBody}
            integrity={integrity}
          />
        )}
      </DetailDrawer>
    </div>
  );
}
