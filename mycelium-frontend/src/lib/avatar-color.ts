// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/** How many tints the avatar palette in globals.css defines. */
const SLOTS = 6;

/** FNV-1a, 32-bit, finished with murmur3's avalanche step.
 *
 *  The avalanche is not optional here. A slot is picked with a small modulo, so
 *  only the bottom few bits are read — and those are exactly the bits FNV-1a
 *  mixes worst, since the last multiply barely disturbs them. Straight off FNV,
 *  six of the ten names in the mock fixtures landed on the same tint. Folding
 *  the high bits down first spreads them evenly. */
function hash(value: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < value.length; i++) {
    h ^= value.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  h ^= h >>> 16;
  h = Math.imul(h, 0x85ebca6b);
  h ^= h >>> 13;
  h = Math.imul(h, 0xc2b2ae35);
  h ^= h >>> 16;
  return h >>> 0;
}

/** A stable tint for an identity — an agent handle, a room name — from the
 *  six-tint avatar palette. Low-chroma on purpose: the job is only to tell one
 *  avatar from the next, and this palette runs across every roster, rail and
 *  row in the app, so it has to stay quieter than the accent rather than
 *  compete with it. (The categorical `--graph-ns-*` hues are the wrong tool —
 *  they are tuned for a single graph where nothing else is competing.)
 *
 *  Derived from the name rather than stored, so the same handle is the same
 *  color on every machine and across a re-render — the point is that you learn
 *  a teammate's color and then spot them without reading. */
export function avatarTint(name: string): string {
  return `var(--avatar-${(hash(name.toLowerCase()) % SLOTS) + 1})`;
}

/** Two-letter monogram: "backend-lead" → BL, "oc-test2" → OT, "main" → MA.
 *  Splits on non-alphanumerics, else takes the first two characters. */
export function initials(name: string): string {
  const parts = name.split(/[^a-z0-9]+/i).filter(Boolean);
  const s = parts.length >= 2 ? parts[0][0] + parts[1][0] : (parts[0] ?? name).slice(0, 2);
  return s.toUpperCase();
}
