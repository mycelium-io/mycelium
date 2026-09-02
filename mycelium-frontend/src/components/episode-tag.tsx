// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { Tooltip } from "@/components/ui/tooltip";

interface Props {
  /** The episode's full URN, e.g. `urn:ioc:mycelium:episode:atlas-migration:e4f1a2`. */
  urn?: string;
  shortId: string;
  /** Opens the episode's thread. Without it the tag is inert. */
  onOpen?: (shortId: string) => void;
}

/**
 * An episode's short id as it reads in chat. A coordination notice names the
 * episode it belongs to, so the name is the way into the record: clicking it
 * opens that episode's thread, the same destination a `?focus=episode:<id>`
 * search hit reaches.
 *
 * Styled like a memory `[[wikilink]]` chip (`markdown-content.tsx`) — one
 * clickable-reference look across chat, whichever kind of record it points at.
 */
export function EpisodeTag({ urn, shortId, onOpen }: Props) {
  const base = "rounded font-mono transition-colors";
  if (!onOpen) {
    return (
      <Tooltip content={urn}>
        <span className={`${base} text-accent`} aria-description={urn}>{shortId}</span>
      </Tooltip>
    );
  }
  // The URN rides along under the action: the tooltip is where a reader checks
  // which episode a bare six characters is.
  const action = urn ? `Open episode ${shortId}\n${urn}` : `Open episode ${shortId}`;
  return (
    <Tooltip content={action}>
      <button
        type="button"
        onClick={() => onOpen(shortId)}
        aria-label={`Open episode ${shortId}`}
        className={`${base} px-1 text-accent hover:bg-accent-soft hover:underline`}
      >
        {shortId}
      </button>
    </Tooltip>
  );
}
