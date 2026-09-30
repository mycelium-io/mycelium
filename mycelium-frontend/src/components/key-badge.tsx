// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useState } from "react";
import { createPortal } from "react-dom";
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

/** How far the corner badge stands proud of its target, in px. */
const PROUD = 6;

/** The key for an action, drawn on the thing it selects while the reveal
 *  modifier is held. This is the whole discoverability story: hold ⌥ and every
 *  navigable target wears its own key, so the scheme teaches itself.
 *
 *  Both variants are positioned out of flow, so holding the modifier never
 *  reflows the row it sits in (a tab strip would otherwise widen and clip).
 *  The overlay covers its target, which needs `relative`. The corner badge
 *  stands proud of its target's top-right corner, so it is drawn over the
 *  page at that corner rather than inside the target: a tab strip that
 *  scrolls sideways clips everything above its own top edge. */
export function KeyBadge({ action, chord: chordProp, overlay = false }: Props) {
  const revealed = useKeyReveal();
  const chord = chordProp ?? (action ? chordFor(action) : undefined);
  // Where the target's corner is on screen, read once the anchor mounts.
  // The badge shows only while the modifier is held, so nothing scrolls under it.
  const [corner, setCorner] = useState<{ top: number; right: number } | null>(null);
  const anchor = useCallback((el: HTMLSpanElement | null) => {
    const box = el?.parentElement?.getBoundingClientRect();
    setCorner(box ? { top: box.top - PROUD, right: window.innerWidth - box.right - PROUD } : null);
  }, []);

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
    <>
      <span ref={anchor} hidden />
      {corner &&
        createPortal(
          <span
            data-key-badge={key}
            aria-hidden
            style={{ top: Math.max(0, corner.top), right: Math.max(0, corner.right) }}
            className="pointer-events-none fixed z-[100] rounded bg-yellow px-1 font-mono text-[10px] font-bold leading-[1.4] text-bg shadow-sm motion-safe:animate-in motion-safe:fade-in-0"
          >
            {key}
          </span>,
          document.body,
        )}
    </>
  );
}
