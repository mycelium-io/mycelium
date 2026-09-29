// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useMemo, useState } from "react";
import { ArrowUpRight, CornerDownLeft } from "lucide-react";
import { highlightJson } from "@/components/l9-inspector";
import { MarkdownContent } from "@/components/markdown-content";
import { Expandable } from "@/components/ui/expandable";
import { fetchMemoryLinks, type MemoryLink } from "@/lib/api";
import { isJsonRawText, prettyPrintJsonRawText } from "@/lib/json-text";
import { linkErrorLabel } from "@/lib/memory-links";
import { fmtAgo } from "@/lib/metrics-format";

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
      <div className="mb-1 flex items-center gap-1.5 px-2 text-micro font-medium text-faint">
        <Icon className="size-3" />
        {title}
        {rows.length > 0 && <span className="font-normal tabular">{rows.length}</span>}
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
  /** Lead the meta line with the memory's key, for a surface that shows it nowhere else. */
  showKey?: boolean;
  /** More controls at the end of the meta line (a tab's Edit and its own page). */
  actions?: React.ReactNode;
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
  showKey = false,
  actions,
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
      {/* What it is in one line (version, who, when, its tags), and how to
          read it at the end of the same line: nothing here needs a grid. */}
      <div className={`flex min-h-8 flex-wrap items-center gap-x-2 gap-y-1 border-b border-border ${pad} py-1 text-micro text-muted-foreground`}>
        {showKey && <span className="font-mono text-text">{memory.key}</span>}
        <span className="tabular" title={memory.file_path || undefined}>
          v{memory.version} · {memory.updated_by || memory.created_by}
          {memory.updated_at && (
            <>
              {" · "}
              <time dateTime={memory.updated_at} title={new Date(memory.updated_at).toLocaleString()}>
                updated {fmtAgo(memory.updated_at)}
              </time>
            </>
          )}
        </span>
        {memory.tags?.map(tag => (
          <span key={tag} className="rounded bg-hairline px-1.5 font-mono text-faint">
            {tag}
          </span>
        ))}
        <div className="ml-auto flex items-center gap-2">
          {raw && rawIsJson && (
            <button
              type="button"
              aria-pressed={effectiveJsonView}
              aria-label="Pretty-print JSON"
              onClick={() => setJsonView(on => !on)}
              className={`transition-colors hover:text-text ${effectiveJsonView ? "text-accent" : ""}`}
            >
              Format JSON
            </button>
          )}
          {([["Rendered", false], ["Raw", true]] as const).map(([label, on]) => (
            <button
              key={label}
              type="button"
              aria-pressed={raw === on}
              onClick={() => setRaw(on)}
              className={`transition-colors hover:text-text ${raw === on ? "text-text" : ""}`}
            >
              {label}
            </button>
          ))}
          {actions}
        </div>
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
