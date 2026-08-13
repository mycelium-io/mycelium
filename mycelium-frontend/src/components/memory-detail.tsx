// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState } from "react";
import { MarkdownContent } from "@/components/markdown-content";

export interface MemoryLike {
  key: string;
  value: unknown;
  content_text?: string;
  version: number;
  created_by: string;
  updated_by?: string;
  updated_at?: string;
  file_path?: string;
}

function formatValue(v: unknown): string {
  if (typeof v === "string") return v;
  if (typeof v === "object" && v !== null) {
    const obj = v as Record<string, unknown>;
    if ("text" in obj) return obj.text as string;
    return JSON.stringify(v, null, 2);
  }
  return String(v);
}

function Meta({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-micro uppercase tracking-wide text-faint">{label}</span>
      <span className="text-label text-text">{children}</span>
    </div>
  );
}

/** Read-only review/audit of one memory: metadata + its markdown body. */
export function MemoryDetail({ memory }: { memory: MemoryLike }) {
  const [raw, setRaw] = useState(false);
  const text = memory.content_text ?? formatValue(memory.value);

  return (
    <div>
      <div className="grid grid-cols-2 gap-x-6 gap-y-4 border-b border-border px-5 py-4">
        <Meta label="Version"><span className="tabular">v{memory.version}</span></Meta>
        <Meta label="Author">{memory.updated_by || memory.created_by}</Meta>
        {memory.updated_at && (
          <Meta label="Updated">
            <span className="tabular">{new Date(memory.updated_at).toLocaleString()}</span>
          </Meta>
        )}
        {memory.file_path && (
          <Meta label="File">
            <span className="break-all font-mono text-micro text-muted-foreground">{memory.file_path}</span>
          </Meta>
        )}
      </div>

      <div className="flex items-center gap-2 px-5 pt-4">
        <div className="flex items-center gap-0.5 rounded-lg border border-border bg-surface p-0.5">
          {([["Rendered", false], ["Raw", true]] as const).map(([label, on]) => (
            <button
              key={label}
              onClick={() => setRaw(on)}
              className={`rounded-md px-2.5 py-1 text-micro font-medium transition-colors ${
                raw === on ? "bg-elevated text-text shadow-sm ring-1 ring-border" : "text-muted-foreground hover:text-text"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="px-5 py-4">
        {raw ? (
          <pre className="overflow-x-auto rounded-lg border border-border bg-surface p-3 font-mono text-micro leading-relaxed text-text whitespace-pre-wrap break-words">
            {text}
          </pre>
        ) : (
          <MarkdownContent className="contrast text-body leading-relaxed">{text}</MarkdownContent>
        )}
      </div>
    </div>
  );
}
