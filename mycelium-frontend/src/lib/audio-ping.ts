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
  if (volume <= 0) return;
  try {
    const c = getContext();
    if (!c) return;
    if (c.state === "suspended") void c.resume();
    const now = c.currentTime;
    tone(c, 880, now, 0.12, volume);
    tone(c, 1318.5, now + 0.09, 0.16, volume * 0.8);
  } catch {
    // Best-effort: a notification sound is never worth failing the caller over.
  }
}
