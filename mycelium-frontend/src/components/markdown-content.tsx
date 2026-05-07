// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

"use client";

import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const MENTION_RE = /(@[\w-]+)/g;

function withMentions(text: string): React.ReactNode {
  const parts = text.split(MENTION_RE);
  return parts.map((part, i) =>
    i % 2 === 1
      ? <span key={i} className="text-accent font-semibold">{part}</span>
      : part,
  );
}

function processNode(node: React.ReactNode): React.ReactNode {
  if (typeof node === "string") return withMentions(node);
  if (Array.isArray(node)) return node.map((n, i) => <React.Fragment key={i}>{processNode(n)}</React.Fragment>);
  if (React.isValidElement(node)) {
    const props = node.props as { children?: React.ReactNode };
    return React.cloneElement(node as React.ReactElement<{ children?: React.ReactNode }>, undefined, processNode(props.children));
  }
  return node;
}

interface Props {
  children: string;
  className?: string;
}

export function MarkdownContent({ children, className }: Props) {
  return (
    <div className={`markdown-body ${className ?? ""}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
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
          // Plain code spans use the underlying renderer (no mentions inside code)
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
