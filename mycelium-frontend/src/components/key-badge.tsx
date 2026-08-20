// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { chordFor, chordKey, isRevealChord } from "@/lib/keymap";
import { useKeyReveal } from "@/components/keymap-provider";

interface Props {
  /** Action id from the keymap; the badge draws that binding's key. */
  action?: string;
  /** A chord to draw directly, for targets the keymap addresses as a run
   *  (the room list's ⌥1…⌥9) rather than one action per target. */
  chord?: string;
  /** Cover the target rather than pinning to its corner — for an avatar or a
   *  lone icon, where the badge can stand in for the thing itself. */
  overlay?: boolean;
}

/** The key for an action, drawn on the thing it selects while the reveal
 *  modifier is held. This is the whole discoverability story: hold ⌥ and every
 *  navigable target wears its own key, so the scheme teaches itself.
 *
 *  Both variants are positioned out of flow, so holding the modifier never
 *  reflows the row it sits in (a tab strip would otherwise widen and clip).
 *  The target needs `relative`. */
export function KeyBadge({ action, chord: chordProp, overlay = false }: Props) {
  const revealed = useKeyReveal();
  const chord = chordProp ?? (action ? chordFor(action) : undefined);
  // Only a reveal chord can be badged: the badge is read with that modifier
  // already held, so drawing a plain key there would be a lie.
  if (!revealed || !chord || !isRevealChord(chord)) return null;

  const key = chordKey(chord);
  if (overlay) {
    return (
      <span
        data-key-badge={key}
        aria-hidden
        className="absolute inset-0 z-10 flex items-center justify-center rounded-md bg-yellow font-mono text-micro font-bold text-bg motion-safe:animate-in motion-safe:fade-in-0"
      >
        {key}
      </span>
    );
  }
  return (
    <span
      data-key-badge={key}
      aria-hidden
      className="absolute -right-1.5 -top-1.5 z-10 rounded bg-yellow px-1 font-mono text-[10px] font-bold leading-[1.4] text-bg shadow-sm motion-safe:animate-in motion-safe:fade-in-0"
    >
      {key}
    </span>
  );
}
