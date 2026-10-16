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

/** `/api/voice/...`, or null for a route this doesn't serve. */
export async function handleVoice(req: Request, rest: string[]): Promise<Response | null> {
  if (rest.length === 1 && req.method === "GET") {
    return json({ state: "ready", detail: "", language: "en", sample_rate: RATE, model: "mock" });
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
