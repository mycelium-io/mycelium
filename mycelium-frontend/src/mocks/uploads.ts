// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// Uploads in fake-backend mode: a session-local store standing in for the
// hub's `uploads/` memories and their blobs. Adding a file writes its memory
// into the room's fixture too, as the hub's upsert does, so the Memory list and
// a memory's detail show it. The hub's checks are mirrored only by extension
// and size; the bytes are kept as sent.

import type { Upload, UploadKind } from "@/lib/api";
import { extensionOf } from "@/lib/uploads";
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
    const uploads = [...store.values()].map((s) => s.record).reverse();
    return json({ uploads, total: uploads.length, accepted: accepted(), max_bytes: MAX_BYTES });
  }

  if (sub.length === 1 && method === "POST") {
    const form = await req.formData();
    const file = form.get("file");
    const who = String(form.get("created_by") ?? "user");
    if (!(file instanceof File)) return json({ detail: "file is required" }, 422);
    const kind = KINDS[extensionOf(file.name)];
    if (!kind) return json({ detail: `${file.name}: .${extensionOf(file.name)} files can't be previewed, so they can't be uploaded` }, 415);
    if (file.size > MAX_BYTES) return json({ detail: `${file.name} is larger than 25.0 MB` }, 413);
    let candidate = safeName(file.name);
    for (let n = 2; store.has(keyFor(candidate)); n++) {
      const dot = safeName(file.name).lastIndexOf(".");
      const base = safeName(file.name);
      candidate = dot > 0 ? `${base.slice(0, dot)}-${n}${base.slice(dot)}` : `${base}-${n}`;
    }
    const key = keyFor(candidate);
    const uploadName = key.slice("uploads/".length);
    const now = new Date().toISOString();
    const bytes = await file.arrayBuffer();
    const record: Upload = {
      name: uploadName,
      key,
      filename: file.name,
      kind: kind[0],
      content_type: kind[1],
      size: bytes.byteLength,
      sha256: `${Date.now().toString(16)}${Math.random().toString(16).slice(2)}`.padEnd(64, "0").slice(0, 64),
      created_by: who,
      created_at: now,
      episode: null,
      url: `/api/rooms/${encodeURIComponent(room)}/uploads/${encodeURIComponent(uploadName)}/raw`,
    };
    store.set(key, { record, bytes });
    const text = kind[0] === "text" ? new TextDecoder().decode(bytes) : `${kind[0]} file \`${file.name}\`.`;
    fx.memories.unshift({ key, value: text, content_text: text, created_by: who, version: 1, updated_at: now });
    return json(record, 201);
  }

  const stored = name ? store.get(keyFor(name)) ?? store.get(`uploads/${name}`) : undefined;
  if (!stored) return name ? json({ detail: "Upload not found" }, 404) : null;

  if (sub.length === 2 && method === "GET") return json(stored.record);
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
