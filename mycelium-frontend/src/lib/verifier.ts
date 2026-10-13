// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// What the app needs to draw the verifier's lines: the words to underline in a
// message, matched the way the message is drawn. The flags themselves come from
// the hub (`fetchVerifierFlags`, `useRoomVerifierFlags`).

import { typeset } from "@/lib/typeset";

/** The shortest piece of a quote worth underlining on its own. */
const MIN_PIECE = 3;

/** The words to underline for a message's flags.
 *
 *  A quote is the verifier's exact text, but the message is drawn in pieces:
 *  inline code is its own element, and prose has its quotes and dashes curled
 *  (`lib/typeset.ts`) before it is matched. So each quote is split around the
 *  message's code spans, and each piece is kept both as written and as drawn.
 *  A piece too short to mean anything on its own is dropped. */
export function claimNeedles(content: string, quotes: string[]): string[] {
  const code = [...content.matchAll(/`([^`\n]+)`/g)].map((m) => m[1]).filter(Boolean);
  const out = new Set<string>();
  for (const quote of quotes) {
    let pieces = [quote];
    for (const span of code) pieces = pieces.flatMap((p) => p.split(span));
    for (const piece of pieces) {
      const trimmed = piece.trim();
      if (trimmed.length < MIN_PIECE) continue;
      out.add(trimmed);
      out.add(typeset(trimmed));
    }
  }
  return [...out];
}
