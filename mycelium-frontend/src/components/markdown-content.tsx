// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import React from "react";
import { MessageSquareText } from "lucide-react";
import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkBreaks from "remark-breaks";
import { Tooltip } from "@/components/ui/tooltip";
import { MarkdownTable } from "@/components/markdown-table";
import { useHighlighter, type Highlight } from "@/components/ui/highlight-text";
import { INTERRUPT_MENTION_SIGIL, SILENT_MENTION_SIGIL } from "@/lib/mentions";
import { typeset } from "@/lib/typeset";

// Mentions, memory links, transclusions, and skill references, in one pass so a
// body is split once. `![[…]]` is listed before `[[…]]` so the transclusion form
// wins. A silent mention `@~handle` (`lib/mentions.ts`) is its own token, drawn
// quieter than one that asked for something; an interrupting `@!handle` is one
// too, with a tooltip saying what it did. A skill reference `/name` (from
// the composer's `/` trigger) is only a token at a word boundary — `(?<![^\s])`
// requires it be preceded by whitespace or the start — so a path, URL, or
// `and/or` never lights up. A thread's short id is eight hex characters
// standing alone: not inside a longer word or hash, a path, a URL or a
// `urn:…:id`, which are written to be read whole.
const TOKEN_RE =
  /(!?\[\[[^\]\n]+\]\]|myc:\/\/[^\s)\]>"'`]*[^\s)\]>"'`.,;:!?]|@~[A-Za-z0-9][\w-]*|@![A-Za-z0-9][\w-]*|@[\w-]+|(?<![^\s])\/[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?|(?<![\w\-/#.:@])[0-9a-f]{8}(?![\w\-/]))/g;

const THREAD_ID = /^[0-9a-f]{8}$/;

/** A task a thread id in prose names: its thread, and what the task is called
 *  (null where several rows share the thread). */
export interface ThreadTarget {
  episode: string;
  title: string | null;
}

const SILENT_HINT = "Mentioned silently, not notified";
const INTERRUPT_HINT = "Interrupts the agent if it's working, so it reads this now";

// `[[mycelium: confidence=0.85 stance=accept]]` is the agent skill's directive
// syntax, not a link. A word followed by a colon *and whitespace* is a
// directive; memory keys never contain ": ".
const DIRECTIVE_RE = /^[A-Za-z][\w-]*:\s/;

/** The plain text under a node.
 *
 *  A `[label](myc://key)` link is rendered as a chip, and the chip needs the
 *  label as a string — but by the time the component runs, the walk above it
 *  may already have replaced that text with the nodes it split it into. Reading
 *  the text back out is what keeps the label the author's word rather than
 *  whatever the last pass wrapped it in. */
function nodeText(node: React.ReactNode): string {
  if (node === null || node === undefined || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(nodeText).join("");
  if (React.isValidElement(node)) return nodeText((node.props as { children?: React.ReactNode }).children);
  return "";
}

interface ParsedLink {
  target: string;
  anchor: string | null;
  label: string | null;
  transclusion: boolean;
}

function slugify(text: string): string {
  return text
    .trim()
    .toLowerCase()
    .replace(/[^\w\s-]/g, "")
    .replace(/[\s_]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

/** Whether a link leads out of this hub: an absolute http(s) or mailto URL on
 *  another origin. A relative link, or one to this hub, stays in the app. */
export function isExternalHref(href: string | undefined, origin?: string): boolean {
  if (!href) return false;
  let url: URL;
  try {
    url = new URL(href);
  } catch {
    return false; // relative: a path in this app
  }
  if (url.protocol === "mailto:") return true;
  if (url.protocol !== "http:" && url.protocol !== "https:") return false;
  const here = origin ?? (typeof window === "undefined" ? "" : window.location.origin);
  return url.origin !== here;
}

/** Normalize a link target to a memory key — mirrors the backend resolver. */
function normalizeKey(target: string): string {
  let key = target.trim();
  if (key.startsWith("myc://")) key = key.slice("myc://".length);
  key = key.replace(/^\/+/, "");
  if (key.startsWith("./")) key = key.slice(2);
  if (key.endsWith(".md")) key = key.slice(0, -".md".length);
  return key.replace(/\/+$/, "");
}

/** Parse one link token, or null when it isn't a link. */
function parseLink(token: string): ParsedLink | null {
  const transclusion = token.startsWith("![[");
  let inner: string;
  if (transclusion) inner = token.slice(3, -2);
  else if (token.startsWith("[[")) inner = token.slice(2, -2);
  else inner = token.slice("myc://".length);

  if (!inner.trim() || DIRECTIVE_RE.test(inner.trim())) return null;

  let label: string | null = null;
  const pipe = inner.indexOf("|");
  if (pipe !== -1) {
    label = inner.slice(pipe + 1).trim() || null;
    inner = inner.slice(0, pipe);
  }
  let anchor: string | null = null;
  const hash = inner.indexOf("#");
  if (hash !== -1) {
    anchor = slugify(inner.slice(hash + 1)) || null;
    inner = inner.slice(0, hash);
  }

  const target = normalizeKey(inner);
  return target ? { target, anchor, label, transclusion } : null;
}

interface LinkProps {
  link: ParsedLink;
  broken: boolean;
  onClick?: (key: string) => void;
}

function MemoryLinkChip({ link, broken, onClick }: LinkProps) {
  const text = link.label ?? (link.anchor ? `${link.target}#${link.anchor}` : link.target);
  const base =
    "inline-flex items-baseline gap-1 rounded px-1 font-mono text-[0.92em] transition-colors";

  if (broken) {
    return (
      <Tooltip content={`${link.target} — no such memory`}>
        <span
          aria-description={`${link.target} — no such memory`}
          className={`${base} text-muted-foreground line-through decoration-red/60`}
        >
          {link.transclusion && <span aria-hidden className="not-italic">⧉</span>}
          {text}
        </span>
      </Tooltip>
    );
  }

  const body = (
    <>
      {link.transclusion && <span aria-hidden className="not-italic">⧉</span>}
      {text}
    </>
  );

  if (!onClick) {
    return <span className={`${base} text-accent`}>{body}</span>;
  }
  const action = link.transclusion ? `Embeds ${link.target}` : `Open ${link.target}`;
  return (
    <Tooltip content={action}>
      {/* aria-description is ARIA 1.3 — jsx-a11y doesn't recognize it yet */}
      {/* eslint-disable-next-line jsx-a11y/role-supports-aria-props */}
      <button
        type="button"
        onClick={() => onClick(link.target)}
        aria-description={action}
        className={`${base} text-accent hover:bg-accent-soft hover:underline`}
      >
        {body}
      </button>
    </Tooltip>
  );
}

/** One memory key drawn as the chip a `[[key]]` in prose becomes, for a line
 *  that names a memory outside any markdown. */
export function MemoryKeyLink({ memoryKey, onClick }: { memoryKey: string; onClick?: (key: string) => void }) {
  const link = { target: normalizeKey(memoryKey), anchor: null, label: null, transclusion: false };
  return <MemoryLinkChip link={link} broken={false} onClick={onClick} />;
}

interface Props {
  children: string;
  className?: string;
  /** Makes memory links clickable. Without it they still render, inert. */
  onLinkClick?: (key: string) => void;
  /** Targets known not to resolve, styled as broken rather than navigable. */
  brokenLinks?: Set<string>;
  /** A find-in-page query to mark in the prose. `active` says this is the
   *  message the find bar has stepped to, so its marks are drawn louder. */
  highlight?: Highlight;
  /** The room's threads by short id. A thread id in the prose that names one
   *  gets a link to its task beside it; any other (a commit hash, say) stays text. */
  threads?: ReadonlyMap<string, ThreadTarget>;
  /** Opens a thread; without it, thread ids stay text. */
  onOpenThread?: (episode: string) => void;
}

/** A thread id that names a task: the id exactly as written, then a small
 *  thread icon that is the link, showing the task on hover and opening its
 *  thread on a click. The app's mark, not words in the agent's mouth. */
function ThreadIdLink({
  id,
  target,
  onOpen,
  code = false,
}: {
  id: string;
  target: ThreadTarget;
  onOpen: (episode: string) => void;
  /** It was written as a code span, and stays one. */
  code?: boolean;
}) {
  return (
    <>
      {code ? <code>{id}</code> : id}
      <Tooltip
        content={
          <span className="flex items-center gap-1.5">
            <MessageSquareText aria-hidden className="size-3 shrink-0" />
            {target.title ?? "Open its thread"}
          </span>
        }
      >
        <button
          type="button"
          onClick={() => onOpen(target.episode)}
          aria-label={`Open ${target.title ? `“${target.title}”` : `thread ${id}`}`}
          // Centered on the line's lowercase letters, not sitting on the baseline.
          className="ml-0.5 inline-flex size-[1.15em] items-center justify-center rounded align-[-0.075em] text-accent/80 transition-colors hover:bg-accent-soft hover:text-accent"
        >
          <MessageSquareText aria-hidden className="size-[0.8em]" />
        </button>
      </Tooltip>
    </>
  );
}

export function MarkdownContent({
  children,
  className,
  onLinkClick,
  brokenLinks,
  highlight,
  threads,
  onOpenThread,
}: Props) {
  const marked = useHighlighter(highlight);

  // Plain prose, drawn with typographic punctuation (`lib/typeset.ts`); the
  // source keeps what was typed.
  const renderProse = React.useCallback(
    (part: string, key: number): React.ReactNode => {
      const text = typeset(part);
      return highlight?.query ? <React.Fragment key={key}>{marked(text)}</React.Fragment> : text;
    },
    [marked, highlight?.query],
  );

  const renderText = React.useCallback(
    (text: string, linkThreads = true): React.ReactNode => {
      const parts = text.split(TOKEN_RE);
      return parts.map((part, i) => {
        // Odd indices are the captured tokens; even indices are plain text.
        if (i % 2 === 0) return renderProse(part, i);
        // A thread id stays as written. One that names a task in this room gets
        // the thread icon after it; any other is plain text, undimmed.
        if (THREAD_ID.test(part)) {
          const target = linkThreads && onOpenThread ? threads?.get(part) : undefined;
          if (target && onOpenThread) return <ThreadIdLink key={i} id={part} target={target} onOpen={onOpenThread} />;
          return renderProse(part, i);
        }
        if (part.startsWith(SILENT_MENTION_SIGIL)) {
          return (
            <Tooltip key={i} content={SILENT_HINT}>
              <span aria-description={SILENT_HINT} className="text-muted-foreground font-semibold">
                {marked(part)}
              </span>
            </Tooltip>
          );
        }
        if (part.startsWith(INTERRUPT_MENTION_SIGIL)) {
          return (
            <Tooltip key={i} content={INTERRUPT_HINT}>
              <span aria-description={INTERRUPT_HINT} className="text-accent font-semibold">
                {marked(part)}
              </span>
            </Tooltip>
          );
        }
        if (part.startsWith("@")) {
          return (
            <span key={i} className="text-accent font-semibold">
              {marked(part)}
            </span>
          );
        }
        // A `/name` skill reference. A skill is a `skills/name` memory, so render
        // it as a chip that opens that memory — the label stays `/name`.
        if (part.startsWith("/")) {
          const target = `skills/${part.slice(1)}`;
          return (
            <MemoryLinkChip
              key={i}
              link={{ target, anchor: null, label: part, transclusion: false }}
              broken={brokenLinks?.has(target) ?? false}
              onClick={onLinkClick}
            />
          );
        }
        const link = parseLink(part);
        if (!link) return part;
        return (
          <MemoryLinkChip
            key={i}
            link={link}
            broken={brokenLinks?.has(link.target) ?? false}
            onClick={onLinkClick}
          />
        );
      });
    },
    [onLinkClick, brokenLinks, marked, renderProse, threads, onOpenThread],
  );

  const processNode = React.useCallback(
    // `linkThreads` is off inside a link's own text, which a button can't sit in.
    function walk(node: React.ReactNode, linkThreads = true): React.ReactNode {
      if (typeof node === "string") return renderText(node, linkThreads);
      if (Array.isArray(node))
        return node.map((n, i) => <React.Fragment key={i}>{walk(n, linkThreads)}</React.Fragment>);
      if (React.isValidElement(node)) {
        // A code span/block is prose *about* syntax, not a link — e.g. a
        // glossary row showing `![[key]]` as an example must stay inert text,
        // not become a chip that navigates to a literal memory named "key".
        // The one exception: a code span that is exactly a thread id, the way
        // agents quote one, links like a bare id and keeps its code look.
        if (node.type === "code" && linkThreads && onOpenThread) {
          const text = (node.props as { children?: React.ReactNode }).children;
          const target = typeof text === "string" && THREAD_ID.test(text) ? threads?.get(text) : undefined;
          if (target) return <ThreadIdLink id={text as string} target={target} onOpen={onOpenThread} code />;
        }
        if (node.type === "code" || node.type === "pre") return node;
        const props = node.props as { children?: React.ReactNode; href?: string };
        return React.cloneElement(
          node as React.ReactElement<{ children?: React.ReactNode }>,
          undefined,
          // A link's own text is walked here, before the link draws it.
          walk(props.children, linkThreads && props.href === undefined),
        );
      }
      return node;
    },
    [renderText, threads, onOpenThread],
  );

  // `[label](myc://key)` is an ordinary markdown link whose scheme no browser
  // can follow. The backend counts it as an edge, so render it as one too.
  const renderAnchor = React.useCallback(
    ({ href, children }: { href?: string; children?: React.ReactNode }) => {
      if (href?.startsWith("myc://")) {
        const link = parseLink(href);
        if (link) {
          const labeled = { ...link, label: link.label ?? (nodeText(children) || link.target) };
          return (
            <MemoryLinkChip
              link={labeled}
              broken={brokenLinks?.has(link.target) ?? false}
              onClick={onLinkClick}
            />
          );
        }
      }
      // A link out of the app opens beside it rather than replacing it; one
      // back into this hub (a room, a memory page) stays in place.
      return isExternalHref(href) ? (
        <a href={href} target="_blank" rel="noopener noreferrer">
          {processNode(children, false)}
        </a>
      ) : (
        <a href={href}>{processNode(children, false)}</a>
      );
    },
    [processNode, onLinkClick, brokenLinks],
  );

  return (
    <div className={`markdown-body ${className ?? ""}`}>
      <ReactMarkdown
        // `remark-breaks` turns a single newline into a line break, the way chat
        // apps do. Agents post terminal-style prose with single newlines; without
        // this CommonMark collapses them into one paragraph and every message walls
        // up. Blank-line paragraph breaks and lists are unaffected. Strikethrough
        // takes `~~`, so two silent `@~` mentions on a line never strike it out.
        remarkPlugins={[[remarkGfm, { singleTilde: false }], remarkBreaks]}
        // `myc://` is an internal scheme the default sanitizer would strip to
        // an empty href; every other URL keeps the stock protocol filtering.
        urlTransform={url => (url.startsWith("myc://") ? url : defaultUrlTransform(url))}
        components={{
          a: renderAnchor,
          p: ({ children }) => <p>{processNode(children)}</p>,
          li: ({ children }) => <li>{processNode(children)}</li>,
          strong: ({ children }) => <strong>{processNode(children)}</strong>,
          em: ({ children }) => <em>{processNode(children)}</em>,
          // The table's own Markdown, sliced from the source by its position,
          // so Copy keeps links, code and emphasis in the cells as written.
          table: ({ children: rows, node }) => {
            const start = node?.position?.start.offset;
            const end = node?.position?.end.offset;
            const source = start !== undefined && end !== undefined ? children.slice(start, end) : undefined;
            return <MarkdownTable source={source}>{rows}</MarkdownTable>;
          },
          // `style` carries the column's alignment (`:--:`, `--:`).
          td: ({ children, style }) => <td style={style}>{processNode(children)}</td>,
          th: ({ children, style }) => <th style={style}>{processNode(children)}</th>,
          h1: ({ children }) => <h1>{processNode(children)}</h1>,
          h2: ({ children }) => <h2>{processNode(children)}</h2>,
          h3: ({ children }) => <h3>{processNode(children)}</h3>,
          h4: ({ children }) => <h4>{processNode(children)}</h4>,
          h5: ({ children }) => <h5>{processNode(children)}</h5>,
          h6: ({ children }) => <h6>{processNode(children)}</h6>,
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
