// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useMemo, useState } from "react";
import { ArrowUpRight, CornerDownLeft, Share2 } from "lucide-react";
import { highlightJson } from "@/components/l9-inspector";
import { MarkdownContent } from "@/components/markdown-content";
import { Expandable } from "@/components/ui/expandable";
import { fetchMemoryLinks, type MemoryLink } from "@/lib/api";
import { isJsonRawText, prettyPrintJsonRawText } from "@/lib/json-text";
import { linkErrorLabel, neighborKeys } from "@/lib/memory-links";

export interface MemoryLike {
  key: string;
  value: unknown;
  content_text?: string;
  version: number;
  created_by: string;
  updated_by?: string | null;
  updated_at?: string;
  file_path?: string;
  tags?: string[];
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
        <span className="flex-shrink-0 text-micro text-red">{linkErrorLabel(error)}</span>
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
  /** Rail peek vs full-page wiki layout. */
  variant?: "rail" | "page";
  /** When set, Rendered mode shows expanded transclusions instead of raw
   *  `![[…]]` markers. */
  renderedBody?: string | null;
  /** Clamp a body taller than this many pixels behind an Expand button. Set by
   *  surfaces that put a conversation under the body, where a long body would
   *  otherwise push it out of reach. Unset renders the body whole. */
  collapseBodyAt?: number | null;
  /** The surface the body sits on, so its fade matches. */
  bodyFade?: "bg" | "paper" | "surface" | "elevated";
}

function NeighborChips({
  keys,
  onNavigate,
  className,
}: {
  keys: string[];
  onNavigate?: (key: string) => void;
  className?: string;
}) {
  if (keys.length === 0) return null;
  return (
    <div className={`border-t border-border py-4 ${className ?? "px-5"}`}>
      <div className="mb-2 flex items-center gap-1.5 text-micro uppercase tracking-wide text-faint">
        <Share2 className="size-3" />
        Related
        <span className="tabular">({keys.length})</span>
      </div>
      <div className="flex flex-wrap gap-2">
        {keys.map(key => (
          onNavigate ? (
            <button
              key={key}
              type="button"
              onClick={() => onNavigate(key)}
              className="rounded-md border border-border bg-surface px-2 py-1 font-mono text-micro text-accent transition-colors hover:bg-hairline"
            >
              {key}
            </button>
          ) : (
            <span
              key={key}
              className="rounded-md border border-border bg-surface px-2 py-1 font-mono text-micro text-muted-foreground"
            >
              {key}
            </span>
          )
        ))}
      </div>
    </div>
  );
}

/** The body, clamped where the surface asked for it and untouched where it
 *  didn't — so a surface that renders the body alone keeps rendering it whole. */
function MaybeExpandable({
  collapseAt,
  fade,
  children,
}: {
  collapseAt: number | null;
  fade: "bg" | "paper" | "surface" | "elevated";
  children: React.ReactNode;
}) {
  if (!collapseAt) return <>{children}</>;
  return (
    <Expandable collapsedHeight={collapseAt} fade={fade} label="the task body">
      {children}
    </Expandable>
  );
}

/** Read-only review/audit of one memory: metadata, its markdown body, its links. */
export function MemoryDetail({
  memory,
  roomName,
  onNavigate,
  variant = "rail",
  renderedBody = null,
  collapseBodyAt = null,
  bodyFade = "bg",
}: Props) {
  const pad = variant === "page" ? "px-6 md:px-8" : "px-5";
  const [raw, setRaw] = useState(false);
  const [jsonView, setJsonView] = useState(false);
  const [outbound, setOutbound] = useState<MemoryLink[]>([]);
  const [backlinks, setBacklinks] = useState<MemoryLink[]>([]);
  const text = memory.content_text ?? formatValue(memory.value);
  const displayText = !raw && renderedBody ? renderedBody : text;
  const rawIsJson = useMemo(() => isJsonRawText(text), [text]);
  // jsonView only means anything in raw mode.
  const effectiveJsonView = raw && jsonView;
  const rawDisplay =
    effectiveJsonView && rawIsJson ? (prettyPrintJsonRawText(text) ?? text) : text;

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
  const neighbors = useMemo(
    () => (variant === "page" ? neighborKeys(memory.key, outbound, backlinks) : []),
    [variant, memory.key, outbound, backlinks],
  );

  return (
    <div>
      {/* A skill is just a `skills/…` memory — no special pane, just a tag. */}
      {memory.key.startsWith("skills/") && (
        <div className={`${pad} pt-4`}>
          <span className="inline-flex items-center rounded-md border border-accent/30 bg-accent-soft/40 px-2 py-0.5 text-micro font-medium text-accent">
            skill
          </span>
        </div>
      )}
      <div className={`grid grid-cols-2 gap-x-6 gap-y-4 border-b border-border ${pad} py-4`}>
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
        {memory.tags && memory.tags.length > 0 && (
          <div className="col-span-2 flex flex-col gap-0.5">
            <span className="text-micro uppercase tracking-wide text-faint">Tags</span>
            <div className="flex flex-wrap gap-1">
              {memory.tags.map(tag => (
                <span
                  key={tag}
                  className="rounded border border-border bg-surface px-1.5 py-0.5 font-mono text-micro text-muted-foreground"
                >
                  {tag}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className={`flex flex-wrap items-center gap-2 ${pad} pt-4`}>
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
        {raw && rawIsJson && (
          <button
            type="button"
            aria-pressed={effectiveJsonView}
            aria-label="Pretty-print JSON"
            onClick={() => setJsonView(on => !on)}
            className={`rounded-lg border px-2.5 py-1 text-micro font-medium transition-colors ${
              effectiveJsonView
                ? "border-accent/40 bg-accent-soft/40 text-accent"
                : "border-border bg-surface text-muted-foreground hover:text-text"
            }`}
          >
            Format JSON
          </button>
        )}
      </div>

      <div className={`${pad} py-4`}>
        <MaybeExpandable collapseAt={collapseBodyAt} fade={bodyFade}>
          {raw ? (
            <pre className="overflow-x-auto rounded-lg border border-border bg-surface p-3 font-mono text-micro leading-relaxed text-text whitespace-pre-wrap break-words">
              {effectiveJsonView ? highlightJson(rawDisplay) : rawDisplay}
            </pre>
          ) : (
            <MarkdownContent
              className={`contrast leading-relaxed ${variant === "page" ? "text-body max-w-prose" : "text-body"}`}
              onLinkClick={onNavigate}
              brokenLinks={broken}
            >
              {displayText}
            </MarkdownContent>
          )}
        </MaybeExpandable>
      </div>

      {variant === "page" && (
        <NeighborChips keys={neighbors} onNavigate={onNavigate} className={pad} />
      )}

      {hasLinks && (
        <div className={`grid gap-4 border-t border-border ${pad} py-4`}>
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
