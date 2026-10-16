// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// Uploads in fake-backend mode: a session-local store standing in for the
// hub's `uploads/` memories and their blobs. Adding a file writes its memory
// into the room's fixture too, as the hub's upsert does, so the Memory list and
// a memory's detail show it. The hub's checks are mirrored only by extension
// and size; the bytes are kept as sent.

import type { Upload, UploadKind, UploadOrigin } from "@/lib/api";
import { extensionOf, uploadKeysIn } from "@/lib/uploads";
import type { RoomFixture } from "./fixtures";

const KINDS: Record<string, [UploadKind, string]> = {
  png: ["image", "image/png"],
  jpg: ["image", "image/jpeg"],
  jpeg: ["image", "image/jpeg"],
  gif: ["image", "image/gif"],
  webp: ["image", "image/webp"],
  pdf: ["pdf", "application/pdf"],
  mp3: ["audio", "audio/mpeg"],
  wav: ["audio", "audio/wav"],
  m4a: ["audio", "audio/mp4"],
  mp4: ["video", "video/mp4"],
  webm: ["video", "video/webm"],
};
const TEXT = "txt md markdown csv tsv json yaml yml toml log py ts tsx js go rs sh sql css html".split(" ");
for (const ext of TEXT) KINDS[ext] = ["text", "text/plain; charset=utf-8"];

const MAX_BYTES = 25 * 1024 * 1024;

interface Stored {
  record: Upload;
  bytes: ArrayBuffer;
}

const STORE = new Map<string, Map<string, Stored>>();

function roomStore(room: string): Map<string, Stored> {
  let store = STORE.get(room);
  if (!store) {
    store = new Map();
    STORE.set(room, store);
  }
  return store;
}

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
}

function safeName(filename: string): string {
  const base = filename.split(/[\\/]/).pop() ?? "file";
  const ascii = base.normalize("NFKD").replace(/[^\x20-\x7e]/g, "").replace(/^\.+/, "");
  const dot = ascii.lastIndexOf(".");
  const stem = (dot > 0 ? ascii.slice(0, dot) : ascii).replace(/[^A-Za-z0-9._-]+/g, "-").replace(/^[-.]+|[-.]+$/g, "") || "file";
  return dot > 0 ? `${stem}.${ascii.slice(dot + 1).toLowerCase()}` : stem;
}

function keyFor(name: string): string {
  return `uploads/${name.endsWith(".md") ? `${name.slice(0, -3)}.markdown` : name}`;
}

const accepted = () => Object.keys(KINDS).sort();

/** A row's title as the board reads it: the first line of its text. */
function titleOf(value: string | Record<string, unknown>, key: string): string {
  const text = typeof value === "string" ? value : String(value.title ?? "");
  return (text.split("\n")[0] || key).replace(/^#+\s*/, "");
}

/** The message each upload was posted with, as the hub's `upload_origins`
 *  reads it: the uploader's own first message that links it, else anyone's. */
function postedIn(fx: RoomFixture, uploaders: Map<string, string>): Map<string, UploadOrigin> {
  const first = new Map<string, UploadOrigin>();
  const own = new Map<string, UploadOrigin>();
  const said = [...fx.messages].sort((a, b) => a.created_at.localeCompare(b.created_at));
  for (const m of said) {
    for (const key of uploadKeysIn(m.content ?? "")) {
      if (own.has(key)) continue;
      const episode = m.episode && !m.episode.endsWith(":live") ? m.episode : null;
      const row = episode ? fx.memories.find((mem) => mem.episode === episode) : undefined;
      const origin: UploadOrigin = {
        message_id: m.id,
        sender: m.sender_handle,
        at: m.created_at,
        episode,
        task: row?.key ?? null,
        task_title: row ? titleOf(row.value, row.key) : null,
      };
      if (!first.has(key)) first.set(key, origin);
      if (uploaders.get(key) === m.sender_handle) own.set(key, origin);
    }
  }
  return new Map([...first, ...own]);
}

/**
 * Store a file as `who`'s upload, as the hub's POST does, and write its memory
 * into the room. A scripted scenario calls this directly when one of its agents
 * uploads something; the caller has already checked the kind.
 */
export function addUpload(room: string, fx: RoomFixture, filename: string, bytes: ArrayBuffer, who: string): Upload {
  const store = roomStore(room);
  const kind = KINDS[extensionOf(filename)];
  let candidate = safeName(filename);
  for (let n = 2; store.has(keyFor(candidate)); n++) {
    const base = safeName(filename);
    const dot = base.lastIndexOf(".");
    candidate = dot > 0 ? `${base.slice(0, dot)}-${n}${base.slice(dot)}` : `${base}-${n}`;
  }
  const key = keyFor(candidate);
  const uploadName = key.slice("uploads/".length);
  const now = new Date().toISOString();
  const record: Upload = {
    name: uploadName,
    key,
    filename,
    kind: kind[0],
    content_type: kind[1],
    size: bytes.byteLength,
    sha256: `${Date.now().toString(16)}${Math.random().toString(16).slice(2)}`.padEnd(64, "0").slice(0, 64),
    created_by: who,
    created_at: now,
    episode: null,
    url: `/api/rooms/${encodeURIComponent(room)}/uploads/${encodeURIComponent(uploadName)}/raw`,
    thumb_url:
      kind[0] === "image" ? `/api/rooms/${encodeURIComponent(room)}/uploads/${encodeURIComponent(uploadName)}/thumb` : null,
  };
  store.set(key, { record, bytes });
  const text = kind[0] === "text" ? new TextDecoder().decode(bytes) : `${kind[0]} file \`${filename}\`.`;
  fx.memories.unshift({ key, value: text, content_text: text, created_by: who, version: 1, updated_at: now });
  return record;
}

/** `/api/rooms/:room/uploads/...`, or null for a route this doesn't serve. */
export async function handleUploads(
  req: Request,
  room: string,
  fx: RoomFixture,
  sub: string[],
): Promise<Response | null> {
  const store = roomStore(room);
  const method = req.method;
  const [, name, tail] = sub.map(decodeURIComponent);

  if (sub.length === 1 && method === "GET") {
    const origins = postedIn(fx, new Map([...store.values()].map((s) => [s.record.key, s.record.created_by])));
    const uploads = [...store.values()].map((s) => ({ ...s.record, posted_in: origins.get(s.record.key) ?? null })).reverse();
    return json({ uploads, total: uploads.length, accepted: accepted(), max_bytes: MAX_BYTES });
  }

  if (sub.length === 1 && method === "POST") {
    const form = await req.formData();
    const file = form.get("file");
    const who = String(form.get("created_by") ?? "user");
    if (!(file instanceof File)) return json({ detail: "file is required" }, 422);
    if (!KINDS[extensionOf(file.name)])
      return json({ detail: `${file.name}: .${extensionOf(file.name)} files can't be previewed, so they can't be uploaded` }, 415);
    if (file.size > MAX_BYTES) return json({ detail: `${file.name} is larger than 25.0 MB` }, 413);
    return json(addUpload(room, fx, file.name, await file.arrayBuffer(), who), 201);
  }

  const stored = name ? store.get(keyFor(name)) ?? store.get(`uploads/${name}`) : undefined;
  if (!stored) return name ? json({ detail: "Upload not found" }, 404) : null;

  if (sub.length === 2 && method === "GET") return json(stored.record);
  // The hub sends a small WebP; here the image itself stands in for it.
  if (sub.length === 3 && tail === "thumb" && method === "GET") {
    if (stored.record.kind !== "image") return json({ detail: "Only an image has a thumbnail" }, 404);
    return new Response(stored.bytes, { headers: { "Content-Type": stored.record.content_type } });
  }
  if (sub.length === 3 && tail === "raw" && method === "GET") {
    const download = new URL(req.url).searchParams.get("download") === "1";
    return new Response(stored.bytes, {
      headers: {
        "Content-Type": stored.record.content_type,
        "Content-Disposition": `${download ? "attachment" : "inline"}; filename*=UTF-8''${encodeURIComponent(stored.record.filename)}`,
        "X-Content-Type-Options": "nosniff",
      },
    });
  }
  if (sub.length === 2 && method === "DELETE") {
    store.delete(stored.record.key);
    const at = fx.memories.findIndex((m) => m.key === stored.record.key);
    if (at >= 0) fx.memories.splice(at, 1);
    return new Response(null, { status: 204 });
  }
  return null;
}
