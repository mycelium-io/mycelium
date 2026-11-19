// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The little markdown a one-line readout can carry: `**bold**`, `*italic*`
 * and `` `code` ``. Nothing else is read as markdown, so a link stays its
 * text (a command can't put something clickable in the sidebar) and a `#` or
 * a `-` is just a character. Built as elements, never as HTML.
 */

import type { ReactNode } from "react";

const TOKEN = /(`[^`\n]+`)|(\*\*(?=\S)[^\n]*?\S\*\*)|(\*(?=[^\s*])[^*\n]*?[^\s*]\*|\*[^\s*]\*)/g;

/** `text` as elements: code first, then bold (which can hold italic), then italic. */
export function inlineMarkdown(text: string, inBold = false): ReactNode[] {
  const out: ReactNode[] = [];
  let at = 0;
  for (const m of text.matchAll(TOKEN)) {
    const [whole, code, bold, italic] = m;
    if (inBold && bold) continue;
    if (m.index > at) out.push(text.slice(at, m.index));
    const key = `${m.index}`;
    if (code) {
      out.push(
        <code key={key} className="rounded bg-hairline px-1 font-mono text-[0.92em]">
          {code.slice(1, -1)}
        </code>,
      );
    } else if (bold) {
      out.push(
        <strong key={key} className="font-semibold">
          {inlineMarkdown(bold.slice(2, -2), true)}
        </strong>,
      );
    } else {
      out.push(<em key={key}>{italic.slice(1, -1)}</em>);
    }
    at = m.index + whole.length;
  }
  if (at < text.length) out.push(text.slice(at));
  return out;
}

export function InlineMarkdown({ text }: { text: string }) {
  return <>{inlineMarkdown(text)}</>;
}
