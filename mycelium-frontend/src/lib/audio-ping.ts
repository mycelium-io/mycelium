// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * Synthesized notification tones (Web Audio oscillators, no audio assets to
 * ship/host). A module-level `AudioContext` is reused across pings and across
 * room switches; browsers require it to be created/resumed from a user
 * gesture, so callers should invoke `primeAudio()` from the click handler
 * that turns pinging on.
 */

export type PingSound = "chime" | "ping" | "tone";

interface SoundSpec {
  /** Frequencies (Hz) played in sequence, one short note each. */
  freqs: number[];
  /** Seconds per note. */
  noteDuration: number;
}

const SOUNDS: Record<PingSound, SoundSpec> = {
  chime: { freqs: [880, 1318.51], noteDuration: 0.16 }, // A5 -> E6 lift
  ping: { freqs: [1046.5], noteDuration: 0.14 }, // C6 single blip
  tone: { freqs: [523.25, 659.25, 783.99], noteDuration: 0.11 }, // C5-E5-G5 arpeggio
};

export const PING_SOUNDS: PingSound[] = ["chime", "ping", "tone"];

let ctx: AudioContext | null = null;

function getContext(): AudioContext | null {
  if (typeof window === "undefined") return null;
  const Ctor =
    window.AudioContext ||
    (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!Ctor) return null;
  if (!ctx) ctx = new Ctor();
  if (ctx.state === "suspended") ctx.resume().catch(() => {});
  return ctx;
}

/** Unlocks audio playback under the browser's user-gesture requirement. Call
 *  this synchronously from the click that enables pinging. */
export function primeAudio(): void {
  getContext();
}

/** Play a short notification tone at the given volume (0-1). Fails silently
 *  if Web Audio isn't available (SSR, unsupported browser, gesture missing). */
export function playPing(sound: PingSound, volume: number): void {
  const audioCtx = getContext();
  if (!audioCtx) return;
  const spec = SOUNDS[sound] ?? SOUNDS.chime;
  const clampedVolume = Math.min(1, Math.max(0, volume));
  const now = audioCtx.currentTime;
  spec.freqs.forEach((freq, i) => {
    const start = now + i * spec.noteDuration;
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.type = "sine";
    osc.frequency.setValueAtTime(freq, start);
    // Quick attack, exponential decay — a soft blip rather than a hard click.
    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.linearRampToValueAtTime(clampedVolume, start + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + spec.noteDuration);
    osc.connect(gain);
    gain.connect(audioCtx.destination);
    osc.start(start);
    osc.stop(start + spec.noteDuration + 0.02);
  });
}
