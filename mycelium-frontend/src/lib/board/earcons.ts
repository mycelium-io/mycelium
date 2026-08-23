// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The board's earcons: one short motif per state change.
 *
 * A steer-lens is only worth having if you can stop watching it, so the surface
 * is built to be heard as well as read — a row arriving that needs you sounds
 * different from one an agent just resolved, and a human's keystroke and an
 * agent's write make the same sound because they are the same write.
 *
 * The vocabulary is intervals, not volume: rising = something opened and wants
 * you, falling = something closed, flat = something moved sideways. Everything
 * is under 400ms and synthesized, so there is no asset to ship and nothing to
 * mistake for the notification chime.
 */

import { motif, type Note } from "@/lib/audio-ping";
import type { Verb } from "./item";

/** A5 as the board's tonic; every motif is an interval off it. */
const A = 880;
const RATIO = {
  minorThird: 1.2,
  fourth: 4 / 3,
  fifth: 1.5,
  octave: 2,
} as const;

export type Earcon =
  | Verb
  | "needs_you"
  | "answer"
  | "capture"
  | "move";

const MOTIFS: Record<Earcon, Note[]> = {
  // Rising minor third, twice: the only motif that interrupts, because it is
  // the only event that wants a human.
  needs_you: [
    { freq: A, at: 0, dur: 0.1 },
    { freq: A * RATIO.minorThird, at: 0.08, dur: 0.14 },
    { freq: A * RATIO.minorThird, at: 0.26, dur: 0.16, gain: 0.55 },
  ],
  // Taking work: one flat, quiet note. Claiming is not an achievement.
  claim: [{ freq: A * 0.75, at: 0, dur: 0.09, gain: 0.7 }],
  // Letting go: the claim's note, a fourth down. A handoff is the same size of
  // event as a claim, in the other direction — not a closing, not a failure.
  release: [
    { freq: A * 0.75, at: 0, dur: 0.08, gain: 0.6 },
    { freq: (A * 0.75) / RATIO.fourth, at: 0.07, dur: 0.11, gain: 0.5 },
  ],
  // Falling fifth into the octave below: the sound of something closing.
  resolve: [
    { freq: A * RATIO.fifth, at: 0, dur: 0.1 },
    { freq: A, at: 0.08, dur: 0.18, gain: 0.8 },
  ],
  // A low pair a semitone apart — deliberately unresolved, like the row.
  block: [
    { freq: A * 0.5, at: 0, dur: 0.14, gain: 0.8 },
    { freq: A * 0.53, at: 0.05, dur: 0.16, gain: 0.6 },
  ],
  unblock: [
    { freq: A * 0.53, at: 0, dur: 0.1, gain: 0.6 },
    { freq: A * 0.75, at: 0.08, dur: 0.14, gain: 0.7 },
  ],
  // Up and out: the row leaves the board for a record that outlives it.
  promote: [
    { freq: A, at: 0, dur: 0.08 },
    { freq: A * RATIO.fourth, at: 0.07, dur: 0.09 },
    { freq: A * RATIO.octave, at: 0.15, dur: 0.2, gain: 0.7 },
  ],
  // A short drop, quieter than everything else: dismissing should feel cheap.
  dismiss: [
    { freq: A * 0.75, at: 0, dur: 0.07, gain: 0.5 },
    { freq: A * 0.6, at: 0.05, dur: 0.1, gain: 0.4 },
  ],
  // A decision settling: the triad, played together rather than in sequence.
  answer: [
    { freq: A, at: 0, dur: 0.22 },
    { freq: A * RATIO.minorThird, at: 0.01, dur: 0.22, gain: 0.6 },
    { freq: A * RATIO.fifth, at: 0.02, dur: 0.26, gain: 0.5 },
  ],
  capture: [{ freq: A * RATIO.fifth, at: 0, dur: 0.07, gain: 0.5 }],
  move: [{ freq: A, at: 0, dur: 0.06, gain: 0.45 }],
};

/** Board sounds sit under the notification chime: ambient, never an alert. */
const MIX = 0.45;

export function earcon(name: Earcon, volume: number): void {
  const notes = MOTIFS[name];
  if (notes) motif(notes, volume * MIX);
}
