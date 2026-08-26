// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import React from "react";
import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkBreaks from "remark-breaks";
import { Tooltip } from "@/components/ui/tooltip";

// Mentions, memory links, transclusions, and skill references, in one pass so a
// body is split once. `![[…]]` is listed before `[[…]]` so the transclusion form
// wins. A skill reference `/name` (from the composer's `/` trigger) is only a
// token at a word boundary — `(?<![^\s])` requires it be preceded by whitespace
// or the start — so a path, URL, or `and/or` never lights up.
const TOKEN_RE =
  /(!?\[\[[^\]\n]+\]\]|myc:\/\/[^\s)\]>"'`]*[^\s)\]>"'`.,;:!?]|@[\w-]+|(?<![^\s])\/[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?)/g;

// `[[mycelium: confidence=0.85 stance=accept]]` is the agent skill's directive
// syntax, not a link. A word followed by a colon *and whitespace* is a
// directive; memory keys never contain ": ".
const DIRECTIVE_RE = /^[A-Za-z][\w-]*:\s/;

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
      {/* aria-description is ARIA 1.3 — jsx-a11y doesn't recognise it yet */}
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

interface Props {
  children: string;
  className?: string;
  /** Makes memory links clickable. Without it they still render, inert. */
  onLinkClick?: (key: string) => void;
  /** Targets known not to resolve, styled as broken rather than navigable. */
  brokenLinks?: Set<string>;
}

export function MarkdownContent({ children, className, onLinkClick, brokenLinks }: Props) {
  const renderText = React.useCallback(
    (text: string): React.ReactNode => {
      const parts = text.split(TOKEN_RE);
      return parts.map((part, i) => {
        // Odd indices are the captured tokens; even indices are plain text.
        if (i % 2 === 0) return part;
        if (part.startsWith("@")) {
          return (
            <span key={i} className="text-accent font-semibold">
              {part}
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
    [onLinkClick, brokenLinks],
  );

  const processNode = React.useCallback(
    function walk(node: React.ReactNode): React.ReactNode {
      if (typeof node === "string") return renderText(node);
      if (Array.isArray(node))
        return node.map((n, i) => <React.Fragment key={i}>{walk(n)}</React.Fragment>);
      if (React.isValidElement(node)) {
        // A code span/block is prose *about* syntax, not a link — e.g. a
        // glossary row showing `![[key]]` as an example must stay inert text,
        // not become a chip that navigates to a literal memory named "key".
        if (node.type === "code" || node.type === "pre") return node;
        const props = node.props as { children?: React.ReactNode };
        return React.cloneElement(
          node as React.ReactElement<{ children?: React.ReactNode }>,
          undefined,
          walk(props.children),
        );
      }
      return node;
    },
    [renderText],
  );

  // `[label](myc://key)` is an ordinary markdown link whose scheme no browser
  // can follow. The backend counts it as an edge, so render it as one too.
  const renderAnchor = React.useCallback(
    ({ href, children }: { href?: string; children?: React.ReactNode }) => {
      if (href?.startsWith("myc://")) {
        const link = parseLink(href);
        if (link) {
          const labelled = { ...link, label: link.label ?? String(children ?? link.target) };
          return (
            <MemoryLinkChip
              link={labelled}
              broken={brokenLinks?.has(link.target) ?? false}
              onClick={onLinkClick}
            />
          );
        }
      }
      return <a href={href}>{processNode(children)}</a>;
    },
    [processNode, onLinkClick, brokenLinks],
  );

  return (
    <div className={`markdown-body ${className ?? ""}`}>
      <ReactMarkdown
        // `remark-breaks` turns a single newline into a line break, the way chat
        // apps do. Agents post terminal-style prose with single newlines; without
        // this CommonMark collapses them into one paragraph and every message walls
        // up. Blank-line paragraph breaks and lists are unaffected.
        remarkPlugins={[remarkGfm, remarkBreaks]}
        // `myc://` is an internal scheme the default sanitizer would strip to
        // an empty href; every other URL keeps the stock protocol filtering.
        urlTransform={url => (url.startsWith("myc://") ? url : defaultUrlTransform(url))}
        components={{
          a: renderAnchor,
          p: ({ children }) => <p>{processNode(children)}</p>,
          li: ({ children }) => <li>{processNode(children)}</li>,
          strong: ({ children }) => <strong>{processNode(children)}</strong>,
          em: ({ children }) => <em>{processNode(children)}</em>,
          td: ({ children }) => <td>{processNode(children)}</td>,
          th: ({ children }) => <th>{processNode(children)}</th>,
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
