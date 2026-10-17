// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// The mic in fake-backend mode: the hub's voice routes with no model. A mic
// that sends audio hears one scripted sentence for every few seconds of it, so
// the composer can be seen filling in as someone talks.

const PHRASES = [
  "Let's add Apple Pay to checkout this week.",
  "Keep card as the default for everyone who isn't on Safari.",
  "And file a task to test it on a real iPhone before we turn it on.",
];

/** About this many seconds of audio per sentence heard. */
const SECONDS_PER_PHRASE = 3;
const RATE = 16000;

const heard = new Map<string, { samples: number; said: number }>();

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
}

/** About how long a sentence takes to say, in seconds per character. */
const SECONDS_PER_CHAR = 0.065;

/** Silence as long as `text` would take to say, as a WAV: the mock hub's
 *  "speech server", so a mention read aloud paces through its words. */
export function silentSpeech(text: string): ArrayBuffer {
  const seconds = Math.min(8, Math.max(0.6, text.length * SECONDS_PER_CHAR));
  const samples = Math.round(seconds * RATE);
  const out = new DataView(new ArrayBuffer(44 + samples * 2));
  const ascii = (at: number, s: string) => [...s].forEach((c, i) => out.setUint8(at + i, c.charCodeAt(0)));
  ascii(0, "RIFF");
  out.setUint32(4, 36 + samples * 2, true);
  ascii(8, "WAVE");
  ascii(12, "fmt ");
  out.setUint32(16, 16, true);
  out.setUint16(20, 1, true);
  out.setUint16(22, 1, true);
  out.setUint32(24, RATE, true);
  out.setUint32(28, RATE * 2, true);
  out.setUint16(32, 2, true);
  out.setUint16(34, 16, true);
  ascii(36, "data");
  out.setUint32(40, samples * 2, true);
  return out.buffer;
}

/** `/api/voice/...`, or null for a route this doesn't serve. */
export async function handleVoice(req: Request, rest: string[]): Promise<Response | null> {
  if (rest.length === 1 && req.method === "GET") {
    return json({ state: "ready", detail: "", language: "en", sample_rate: RATE, model: "mock", speech: true });
  }
  if (rest[1] === "speech" && rest.length === 2 && req.method === "POST") {
    const { text } = (await req.json()) as { text?: string };
    if (!text) return json({ detail: "Nothing to say" }, 422);
    return new Response(silentSpeech(text), { headers: { "Content-Type": "audio/wav" } });
  }
  if (rest[1] !== "sessions" || rest.length !== 3) return null;
  const sid = rest[2];
  if (req.method === "DELETE") {
    heard.delete(sid);
    return new Response(null, { status: 204 });
  }
  if (req.method !== "POST") return null;
  const final = new URL(req.url).searchParams.get("final") === "true";
  const bytes = (await req.arrayBuffer()).byteLength;
  const mic = heard.get(sid) ?? { samples: 0, said: 0 };
  mic.samples += bytes / 2;
  const due = Math.floor(mic.samples / (SECONDS_PER_PHRASE * RATE));
  const texts: string[] = [];
  while (mic.said < due || (final && mic.said === 0 && mic.samples > 0)) {
    texts.push(PHRASES[mic.said % PHRASES.length]);
    mic.said += 1;
  }
  if (final) heard.delete(sid);
  else heard.set(sid, mic);
  return json({ texts, speaking: !final && mic.samples > 0 });
}
