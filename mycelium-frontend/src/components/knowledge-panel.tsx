// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchCfnConcepts, fetchCfnNeighbors } from "@/lib/api";
import type { CfnConcept, CfnNeighborsResponse } from "@/lib/api";

interface Props {
  masId: string | null | undefined;
}

type LoadState = "idle" | "loading" | "ok" | "empty" | "error";

export function KnowledgePanel({ masId }: Props) {
  const [concepts, setConcepts] = useState<CfnConcept[]>([]);
  const [state, setState] = useState<LoadState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [neighbors, setNeighbors] = useState<Record<string, CfnNeighborsResponse>>({});

  const load = useCallback(async () => {
    if (!masId) {
      setState("idle");
      return;
    }
    setState("loading");
    setError(null);
    try {
      const data = await fetchCfnConcepts(masId, 50);
      if (!data) {
        setState("error");
        setError("CFN graph not available for this MAS");
        return;
      }
      setConcepts(data.nodes || []);
      setState((data.nodes || []).length === 0 ? "empty" : "ok");
    } catch (e) {
      setState("error");
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }, [masId]);

  useEffect(() => {
    load();
  }, [load]);

  const toggleNeighbors = async (concept: CfnConcept) => {
    const key = concept.id || concept.vid || "";
    if (!key || !masId) return;
    if (expanded === key) {
      setExpanded(null);
      return;
    }
    setExpanded(key);
    if (!neighbors[key]) {
      const data = await fetchCfnNeighbors(masId, key);
      if (data) setNeighbors(prev => ({ ...prev, [key]: data }));
    }
  };

  if (!masId) {
    return (
      <div className="px-4 py-10 text-center text-muted/60 text-sm">
        Room is not linked to a MAS.
        <div className="text-xs text-muted/40 mt-2 font-mono">
          Set <code className="text-accent/70">mas_id</code> on the room to view CFN knowledge.
        </div>
      </div>
    );
  }

  if (state === "loading") {
    return <div className="px-4 py-10 text-center text-muted/60 text-sm">Loading CFN graph…</div>;
  }

  if (state === "error") {
    return (
      <div className="px-4 py-10 text-center text-muted/60 text-sm">
        <div className="text-red-400/80">CFN graph unavailable</div>
        {error && <div className="text-xs text-muted/40 mt-2 font-mono">{error}</div>}
        <button
          onClick={load}
          className="mt-4 text-xs text-accent/80 hover:text-accent underline-offset-2 hover:underline"
        >
          retry
        </button>
      </div>
    );
  }

  if (state === "empty") {
    return (
      <div className="px-4 py-10 text-center text-muted/60 text-sm">
        No concepts ingested yet.
        <div className="text-xs text-muted/40 mt-2 font-mono">
          Graph exists but is empty for <span className="text-accent/70">{masId}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 py-3 border-b border-border flex items-center gap-2 flex-nowrap">
        <span className="text-xs text-muted shrink-0">mas_id</span>
        <code
          className="text-xs font-mono text-accent/80 truncate min-w-0 flex-1"
          title={masId}
        >
          {masId}
        </code>
        <span className="text-[10px] text-muted/50 font-mono whitespace-nowrap shrink-0">
          {concepts.length} concepts
        </span>
        <button
          onClick={load}
          className="text-[10px] text-muted hover:text-white font-bold uppercase tracking-wider whitespace-nowrap shrink-0"
        >
          refresh
        </button>
      </div>
      <div className="flex-1 overflow-y-auto px-4 py-2 space-y-1">
        {concepts.map((c, i) => {
          const key = c.id || c.vid || `idx-${i}`;
          const isExpanded = expanded === key;
          const neigh = neighbors[key];
          const neighList = (neigh?.neighbors as Array<Record<string, unknown>>) || [];
          return (
            <div key={key} className="py-2 border-b border-border/30 last:border-b-0">
              <button
                onClick={() => toggleNeighbors(c)}
                className="w-full flex items-center gap-2 text-left group flex-nowrap"
              >
                <svg
                  width="10" height="10" viewBox="0 0 10 10" fill="currentColor"
                  className={`text-muted transition-transform shrink-0 ${isExpanded ? "rotate-90" : ""}`}
                >
                  <path d="M3 1L8 5L3 9Z" />
                </svg>
                <span
                  className="font-mono text-sm text-accent group-hover:text-white truncate min-w-0 flex-1"
                  title={c.name || c.id || c.vid || ""}
                >
                  {c.name || c.id || c.vid || "(unnamed)"}
                </span>
                {c.label && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted/10 text-muted font-bold shrink-0">
                    {c.label}
                  </span>
                )}
                <span
                  className="text-[10px] text-muted/30 font-mono truncate max-w-[120px] shrink-0"
                  title={c.id}
                >
                  {c.id}
                </span>
              </button>
              {isExpanded && (
                <div className="ml-5 mt-2 space-y-1">
                  {neigh === undefined ? (
                    <div className="text-[11px] text-muted/60">Loading neighbors…</div>
                  ) : neighList.length === 0 ? (
                    <div className="text-[11px] text-muted/60">No neighbors</div>
                  ) : (
                    neighList.map((n, ni) => {
                      const name = (n.name as string) || (n.id as string) || "(unnamed)";
                      const rel = (n.relation as string) || (n.edge as string) || "";
                      return (
                        <div key={ni} className="flex items-center gap-2 text-[11px]">
                          <span className="w-1 h-1 rounded-full bg-accent/50 shrink-0" />
                          <span className="font-mono text-white/70">{name}</span>
                          {rel && <span className="text-muted/60 italic">{rel}</span>}
                        </div>
                      );
                    })
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
