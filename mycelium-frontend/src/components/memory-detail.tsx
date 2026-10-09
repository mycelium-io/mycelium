// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useMemo, useState } from "react";
import { ArrowUpRight, CornerDownLeft, Download, FileImage, FileText } from "lucide-react";
import { highlightJson } from "@/components/message-inspector";
import { MarkdownContent } from "@/components/markdown-content";
import { Expandable } from "@/components/ui/expandable";
import { fetchMemoryLinks, type MemoryLink } from "@/lib/api";
import { isJsonRawText, prettyPrintJsonRawText } from "@/lib/json-text";
import { linkErrorLabel } from "@/lib/memory-links";
import { fmtAgo } from "@/lib/metrics-format";
import { useRoomUploads } from "@/lib/room-data";
import { downloadUrl, formatBytes, isUploadKey, kindLabel } from "@/lib/uploads";
import { cn } from "@/lib/utils";
import { Button, buttonVariants } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/tooltip";
import { UploadPreview } from "@/components/uploads/upload-preview";

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
  /** Head it with a sticky toolbar naming the key, for a surface that shows it nowhere else. */
  showKey?: boolean;
  /** More controls at the end of the header (a tab's Edit and its own page). */
  actions?: React.ReactNode;
  /** Classes for everything under the header, so a page can center its body
   *  while the toolbar spans the width. */
  bodyClassName?: string;
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

/** A key as breadcrumbs, the way the editor's header writes it. */
function KeyCrumbs({ memoryKey }: { memoryKey: string }) {
  const parts = memoryKey.split("/");
  return (
    <h1 className="max-w-full shrink-0 truncate font-mono text-label" title={memoryKey}>
      {parts.map((part, i) => (
        <span key={i} className={i === parts.length - 1 ? "text-text" : "text-muted-foreground"}>
          {i > 0 && <span className="text-faint">/</span>}
          {part}
        </span>
      ))}
    </h1>
  );
}

/** Rendered or Raw, as one control rather than two words. */
function ViewToggle({ raw, onChange }: { raw: boolean; onChange: (raw: boolean) => void }) {
  return (
    <div className="flex items-center rounded-md bg-hairline/60 p-0.5">
      {([["Rendered", false], ["Raw", true]] as const).map(([label, on]) => (
        <button
          key={label}
          type="button"
          aria-pressed={raw === on}
          onClick={() => onChange(on)}
          className={cn(
            "flex h-5 items-center rounded px-2 text-micro transition-colors",
            raw === on ? "bg-bg text-text shadow-sm" : "text-muted-foreground hover:text-text",
          )}
        >
          {label}
        </button>
      ))}
    </div>
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
  bodyClassName,
}: Props) {
  const pad = variant === "page" ? "px-6 md:px-8" : "px-5";
  const [raw, setRaw] = useState(false);
  // An upload's file stands where its body would; the body (a line about the
  // file, or a text file's text) is still there under Raw.
  const isUpload = Boolean(roomName) && isUploadKey(memory.key);
  const { uploads, loading: uploadsLoading } = useRoomUploads(isUpload ? (roomName ?? "") : "");
  const upload = isUpload ? uploads.find((u) => u.key === memory.key) : undefined;
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

  const facts = (
    <span className="tabular" title={memory.file_path || undefined}>
      v{memory.version} · {memory.updated_by || memory.created_by}
      {memory.updated_at && (
        <>
          {" · "}
          <time dateTime={memory.updated_at} title={new Date(memory.updated_at).toLocaleString()}>
            {fmtAgo(memory.updated_at)}
          </time>
        </>
      )}
      {upload && ` · ${kindLabel(upload.kind)} · ${formatBytes(upload.size)}`}
    </span>
  );
  const tags = memory.tags?.map(tag => (
    <span key={tag} className="flex-shrink-0 rounded bg-hairline px-1.5 font-mono text-faint">
      {tag}
    </span>
  ));
  // A skill is just a `skills/…` memory — no special pane, just a tag.
  const skill = memory.key.startsWith("skills/") && (
    <span className="flex-shrink-0 rounded border border-accent/30 bg-accent-soft/40 px-1.5 text-micro font-medium text-accent">
      skill
    </span>
  );
  const controls = (
    <div className="ml-auto flex flex-shrink-0 items-center gap-1">
      {raw && rawIsJson && (
        <Button
          variant="ghost"
          size="xs"
          aria-pressed={effectiveJsonView}
          aria-label="Pretty-print JSON"
          onClick={() => setJsonView(on => !on)}
          className={effectiveJsonView ? "text-accent" : undefined}
        >
          Format JSON
        </Button>
      )}
      <ViewToggle raw={raw} onChange={setRaw} />
      {upload && (
        <Tooltip content={`Download ${upload.filename}`}>
          <a
            href={downloadUrl(upload)}
            download={upload.filename}
            aria-label="Download"
            className={cn(buttonVariants({ variant: "ghost", size: "xs" }), "gap-1")}
          >
            <Download className="size-3.5" />
            <span className="hidden @2xl:inline">Download</span>
          </a>
        </Tooltip>
      )}
      {actions}
    </div>
  );

  return (
    <div>
      {showKey ? (
        // The page's toolbar, the editor's header in read mode: the key as
        // breadcrumbs, what it is in a quiet line beside it, and the controls.
        <header className="sticky top-0 z-10 flex min-h-10 items-center gap-3 border-b border-border bg-paper/95 px-5 py-1.5 backdrop-blur-sm">
          <div className="flex min-w-0 flex-1 items-center gap-2">
            {upload ? (
              <FileImage className="size-3.5 flex-shrink-0 text-muted-foreground" />
            ) : (
              <FileText className="size-3.5 flex-shrink-0 text-muted-foreground" />
            )}
            <KeyCrumbs memoryKey={memory.key} />
            {skill}
            {/* Gives way before the key does. */}
            <span className="hidden min-w-0 shrink-[100] truncate text-micro text-faint @xl:block">
              {facts}
              {memory.tags?.map(tag => (
                <span key={tag} className="ml-2 rounded bg-hairline px-1.5 font-mono">
                  {tag}
                </span>
              ))}
            </span>
          </div>
          {controls}
        </header>
      ) : (
        <header className={`flex min-h-8 flex-wrap items-center gap-x-2 gap-y-1 border-b border-border ${pad} py-1 text-micro text-muted-foreground`}>
          {skill}
          {facts}
          {tags}
          {controls}
        </header>
      )}

      <div className={bodyClassName}>
      {isUpload && !raw && (
        <div className={`${pad} pt-4`}>
          {upload ? (
            <UploadPreview upload={upload} onOpenMemory={onNavigate} />
          ) : uploadsLoading ? null : (
            <p className="text-label text-muted-foreground">This upload&apos;s file isn&apos;t on the hub.</p>
          )}
        </div>
      )}

      <div className={`${pad} py-4`} hidden={isUpload && !raw}>
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
    </div>
  );
}
