// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useMemo, useState } from "react";
import { ArrowUpRight, CornerDownLeft } from "lucide-react";
import { MarkdownContent } from "@/components/markdown-content";
import { fetchMemoryLinks, type MemoryLink } from "@/lib/api";

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

// Why a link doesn't resolve, in words. The API reports codes; only the UI has
// to phrase them.
const LINK_ERRORS: Record<string, string> = {
  not_found: "no such memory",
  no_anchor: "no such section",
  not_expandable: "target is not expandable",
  cross_room: "cross-room links are not supported",
};

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

function linkTarget(link: MemoryLink): string {
  return link.anchor ? `${link.target}#${link.anchor}` : link.target;
}

function LinkRow({
  label,
  kind,
  error,
  onOpen,
}: {
  label: string;
  kind: string;
  error?: string | null;
  onOpen?: () => void;
}) {
  const content = (
    <>
      <span className="font-mono text-label truncate">{label}</span>
      <span className="ml-auto flex-shrink-0 text-micro text-faint">{kind}</span>
      {error && (
        <span className="flex-shrink-0 text-micro text-red">{LINK_ERRORS[error] ?? error}</span>
      )}
    </>
  );

  if (error || !onOpen) {
    return (
      <div className="flex items-baseline gap-2 px-2 py-1 text-muted-foreground">{content}</div>
    );
  }
  return (
    <button
      onClick={onOpen}
      className="flex w-full items-baseline gap-2 rounded px-2 py-1 text-left text-accent transition-colors hover:bg-hairline"
    >
      {content}
    </button>
  );
}

/** A row's display text and the memory it opens — these differ by direction:
 *  an outbound row points at its target, a backlink points back at its source. */
interface LinkRowData {
  label: string;
  navKey: string;
  kind: string;
  error?: string | null;
}

function LinkGroup({
  title,
  icon: Icon,
  rows,
  empty,
  onNavigate,
}: {
  title: string;
  icon: typeof ArrowUpRight;
  rows: LinkRowData[];
  empty: string;
  onNavigate?: (key: string) => void;
}) {
  return (
    <div>
      <div className="mb-1 flex items-center gap-1.5 text-micro uppercase tracking-wide text-faint">
        <Icon className="size-3" />
        {title}
        {rows.length > 0 && <span className="tabular">({rows.length})</span>}
      </div>
      {rows.length === 0 ? (
        <p className="px-2 py-1 text-label text-faint">{empty}</p>
      ) : (
        rows.map((row, i) => (
          <LinkRow
            key={i}
            label={row.label}
            kind={row.kind}
            error={row.error}
            onOpen={onNavigate ? () => onNavigate(row.navKey) : undefined}
          />
        ))
      )}
    </div>
  );
}

interface Props {
  memory: MemoryLike;
  roomName?: string;
  /** Opens another memory by key — supplied by whatever owns the selection. */
  onNavigate?: (key: string) => void;
}

/** Read-only review/audit of one memory: metadata, its markdown body, its links. */
export function MemoryDetail({ memory, roomName, onNavigate }: Props) {
  const [raw, setRaw] = useState(false);
  const [outbound, setOutbound] = useState<MemoryLink[]>([]);
  const [backlinks, setBacklinks] = useState<MemoryLink[]>([]);
  const text = memory.content_text ?? formatValue(memory.value);

  useEffect(() => {
    if (!roomName) return;
    let live = true;
    fetchMemoryLinks(roomName, memory.key).then(links => {
      if (!live) return;
      setOutbound(links.outbound);
      setBacklinks(links.backlinks);
    });
    return () => {
      live = false;
    };
  }, [roomName, memory.key]);

  const broken = useMemo(
    () => new Set(outbound.filter(l => !l.resolved).map(l => l.target)),
    [outbound],
  );

  const outboundRows = useMemo<LinkRowData[]>(
    () =>
      outbound.map(link => ({
        label: linkTarget(link),
        navKey: link.target,
        kind: link.relation ?? link.kind,
        error: link.error,
      })),
    [outbound],
  );

  const backlinkRows = useMemo<LinkRowData[]>(
    () =>
      backlinks.map(link => ({
        label: link.source ?? link.target,
        navKey: link.source ?? link.target,
        kind: link.relation ?? link.kind,
      })),
    [backlinks],
  );

  const hasLinks = outbound.length > 0 || backlinks.length > 0;

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
          <MarkdownContent
            className="contrast text-body leading-relaxed"
            onLinkClick={onNavigate}
            brokenLinks={broken}
          >
            {text}
          </MarkdownContent>
        )}
      </div>

      {/* Backlinks are the point: before changing this memory, they show
          exactly which others depend on what it says. */}
      {hasLinks && (
        <div className="grid gap-4 border-t border-border px-5 py-4">
          <LinkGroup
            title="Links to"
            icon={ArrowUpRight}
            rows={outboundRows}
            empty="Nothing"
            onNavigate={onNavigate}
          />
          <LinkGroup
            title="Referenced by"
            icon={CornerDownLeft}
            rows={backlinkRows}
            empty="Nothing links here"
            onNavigate={onNavigate}
          />
        </div>
      )}
    </div>
  );
}
