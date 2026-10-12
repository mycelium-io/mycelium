// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/** Sporelings: an agent's avatar drawn as a small forest creature, from its handle.
 *
 *  The handle is the seed. It picks the creature's family and every feature, so
 *  the same agent is the same creature on every machine, with nothing stored.
 *  Color is not part of this: the creature wears the handle's existing avatar
 *  tint (`avatarTint`), so nobody changes color when this is turned on.
 *
 *  Engines (the aligner, the conductor) are always lanterns, so the hub's own
 *  helpers read as something other than an agent. People are never creatures;
 *  they keep their initials. */

/** The families an agent can be. Engines are `lantern`, which no agent is. */
export const AGENT_FAMILIES = ["cap", "owl", "moth", "slime", "snail"] as const;
export type Family = (typeof AGENT_FAMILIES)[number] | "lantern";

export type CapShape = "dome" | "cone" | "flat" | "bell";
export type OwlTufts = "ears" | "crest" | "none";

/** Everything a seed decides. Drawing reads this and nothing else. */
export interface Genome {
  family: Family;
  /** Eyes a little closer or wider apart, so two creatures of a family differ. */
  eyeGap: number;
  /** Degrees the creature leans, kept small so it still sits in its circle. */
  tilt: number;
  cap: CapShape;
  tufts: OwlTufts;
  /** Spots on a cap (ignored by the other families). */
  spots: number;
}

/** cyrb53: fast, well-spread, and stable across engines. */
function hash(value: string, seed = 0): number {
  let h1 = 0xdeadbeef ^ seed;
  let h2 = 0x41c6ce57 ^ seed;
  for (let i = 0; i < value.length; i++) {
    const ch = value.charCodeAt(i);
    h1 = Math.imul(h1 ^ ch, 2654435761);
    h2 = Math.imul(h2 ^ ch, 1597334677);
  }
  h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
  h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
  return 4294967296 * (2097151 & h2) + (h1 >>> 0);
}

/** A seeded stream of numbers in [0, 1) (mulberry32). */
function stream(seed: string): () => number {
  let a = hash(seed) >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** The creature a handle is. `engine` makes it a lantern whatever the seed. */
export function genome(handle: string, engine = false): Genome {
  const seed = handle.trim().toLowerCase();
  const next = stream(`sporeling:${seed}`);
  const pick = <T,>(xs: readonly T[]): T => xs[Math.floor(next() * xs.length)];
  // The family has its own hash, so tuning the features below never moves an
  // agent to a different family.
  const family: Family = engine ? "lantern" : AGENT_FAMILIES[hash(`family:${seed}`) % AGENT_FAMILIES.length];
  return {
    family,
    eyeGap: 0.9 + next() * 0.25,
    tilt: Math.round((next() - 0.5) * 10),
    cap: pick(["dome", "cone", "flat", "bell"] as const),
    tufts: pick(["ears", "crest", "none"] as const),
    spots: 2 + Math.floor(next() * 3),
  };
}

/** How much detail fits at a given size, in CSS pixels. Below 28px a creature is
 *  a glyph: its silhouette and two dots, kept inside the circle. */
export type Detail = "glyph" | "simple";
export function detailFor(px: number): Detail {
  return px < 28 ? "glyph" : "simple";
}

/** The pixel size a Tailwind `size-N` class gives, or the avatar's default. */
export function pxOfSizeClass(className: string | undefined, fallback = 32): number {
  const match = className?.match(/(?:^|\s)size-(\d+(?:\.\d+)?)(?:\s|$)/);
  return match ? Number(match[1]) * 4 : fallback;
}
