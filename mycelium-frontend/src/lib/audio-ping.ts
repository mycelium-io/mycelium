// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// Dependency-free notification chime: two short synthesized tones via the Web
// Audio API. No asset to ship, no license to track. Browsers block audio
// until a user gesture unlocks the page's AudioContext, so `primeAudio()`
// should be wired to the first click/keydown the app sees; `ping()` before
// that is a silent no-op (caught, never throws into a render path).

let ctx: AudioContext | null = null;

function getContext(): AudioContext | null {
  if (typeof window === "undefined") return null;
  const Ctor = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!Ctor) return null;
  if (!ctx) ctx = new Ctor();
  return ctx;
}

/** Unlock audio playback on the first user gesture (click/keydown/touch). */
export function primeAudio(): void {
  const c = getContext();
  if (c && c.state === "suspended") void c.resume();
}

/** One note in a motif: a frequency, an offset from the motif's start, a length. */
export interface Note {
  freq: number;
  at: number;
  dur: number;
  /** Relative to the caller's volume; 1 is the full requested loudness. */
  gain?: number;
}

/**
 * Play a short motif on the shared context. Exported so a surface can speak in
 * more than one sound — see `board/earcons.ts` — without opening a second
 * AudioContext or shipping an asset.
 */
export function motif(notes: Note[], volume = 0.5): void {
  if (volume <= 0) return;
  try {
    const c = getContext();
    if (!c) return;
    if (c.state === "suspended") void c.resume();
    const now = c.currentTime;
    for (const note of notes) {
      tone(c, note.freq, now + note.at, note.dur, volume * (note.gain ?? 1));
    }
  } catch {
    // Best-effort: a sound is never worth failing the caller over.
  }
}

function tone(c: AudioContext, freq: number, start: number, duration: number, volume: number): void {
  const osc = c.createOscillator();
  const gain = c.createGain();
  osc.type = "sine";
  osc.frequency.value = freq;
  gain.gain.setValueAtTime(0, start);
  gain.gain.linearRampToValueAtTime(volume, start + 0.01);
  gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
  osc.connect(gain);
  gain.connect(c.destination);
  osc.start(start);
  osc.stop(start + duration);
}

/** Play a short two-note chime. ``volume`` is 0–1; a no-op below ~0. */
export function ping(volume = 0.5): void {
  motif(
    [
      { freq: 880, at: 0, dur: 0.12 },
      { freq: 1318.5, at: 0.09, dur: 0.16, gain: 0.8 },
    ],
    volume,
  );
}
