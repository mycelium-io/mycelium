// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import type { ReactNode } from "react";

// One pass over pretty-printed JSON: quoted strings (key when a colon follows,
// else value), literals, and numbers. Punctuation/whitespace fall between matches.
const JSON_TOKENS = /("(?:\\.|[^"\\])*")(\s*:)?|\b(true|false|null)\b|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/g;

/** JSON syntax highlight: colors keys, strings, numbers, literals. */
export function highlightJson(src: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let key = 0;
  for (const m of src.matchAll(JSON_TOKENS)) {
    const start = m.index ?? 0;
    if (start > last) out.push(src.slice(last, start));
    const [full, str, colon, lit, num] = m;
    if (str !== undefined) {
      out.push(
        colon ? (
          <span key={key++} className="text-accent">{str}</span>
        ) : (
          <span key={key++} style={{ color: "var(--green)" }}>{str}</span>
        ),
      );
      if (colon) out.push(colon);
    } else if (lit !== undefined) {
      out.push(<span key={key++} className="text-red">{lit}</span>);
    } else if (num !== undefined) {
      out.push(<span key={key++} className="text-yellow">{num}</span>);
    }
    last = start + full.length;
  }
  if (last < src.length) out.push(src.slice(last));
  return out;
}
