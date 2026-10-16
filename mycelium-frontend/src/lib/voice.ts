// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// The composer's mic, the parts that are plain arithmetic. The hub hears
// 16 kHz mono 16-bit PCM (`routes/voice.py`); a browser records at its own
// rate, usually 48 kHz, so audio is averaged down to 16 kHz here before it
// goes. Int16Array is in the machine's byte order, which is little-endian on
// every machine the app runs on, as the hub expects.

/** How often a chunk of audio goes to the hub while the mic is on, in ms. */
export const CHUNK_MS = 300;

/** `input` at `fromRate`, averaged down to `toRate`. A rate at or below the
 *  target is passed through, since the hub can't use a higher one anyway. */
export function downsample(input: Float32Array, fromRate: number, toRate: number): Float32Array {
  if (fromRate <= toRate) return input;
  const ratio = fromRate / toRate;
  const out = new Float32Array(Math.floor(input.length / ratio));
  for (let i = 0; i < out.length; i++) {
    const start = Math.floor(i * ratio);
    const end = Math.min(input.length, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = start; j < end; j++) sum += input[j];
    out[i] = end > start ? sum / (end - start) : 0;
  }
  return out;
}

/** Float samples in [-1, 1] as 16-bit PCM, clipped. */
export function toPcm16(samples: Float32Array): Int16Array {
  const out = new Int16Array(samples.length);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out;
}

/** Join chunks of PCM into one. */
export function concatPcm(chunks: Int16Array[]): Int16Array {
  const out = new Int16Array(chunks.reduce((n, c) => n + c.length, 0));
  let at = 0;
  for (const c of chunks) {
    out.set(c, at);
    at += c.length;
  }
  return out;
}

/** The draft with something just said added to its end, one space between. */
export function appendHeard(draft: string, heard: string): string {
  const text = heard.trim();
  if (!text) return draft;
  if (!draft.trim()) return text;
  return /\s$/.test(draft) ? `${draft}${text}` : `${draft} ${text}`;
}

/** A random id for one open mic, in the hex the hub's route takes. */
export function newVoiceSessionId(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

/** Whether the Mac app will refuse this page the microphone: it gives it only
 *  to its own hub, which it serves on this machine's loopback, so a page on
 *  any other host inside the app (its client mode, showing another hub) is
 *  refused. A browser decides for itself, so there this is always false. */
export function appRefusesMic(hostname: string, inDesktopApp: boolean): boolean {
  return inDesktopApp && !["127.0.0.1", "localhost", "[::1]"].includes(hostname);
}

/** What a mic that won't start says, from the browser's error. */
export function micErrorMessage(err: unknown): string {
  const name = err instanceof DOMException ? err.name : "";
  if (name === "NotAllowedError" || name === "SecurityError") {
    return "The microphone is blocked. Allow it for this page and turn the mic on again.";
  }
  if (name === "NotFoundError" || name === "OverconstrainedError") return "There's no microphone to listen with.";
  if (name === "NotReadableError") return "Another app is using the microphone.";
  return err instanceof Error ? err.message : String(err);
}

// The worklet that hands the page what the mic records, a block at a time.
// Loaded from a Blob URL so it needs no file of its own in the build.
export const CAPTURE_WORKLET = `
class Capture extends AudioWorkletProcessor {
  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (channel) this.port.postMessage(channel.slice(0));
    return true;
  }
}
registerProcessor("mycelium-capture", Capture);
`;
