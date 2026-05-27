// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

function getBackendUrl(): string {
  if (process.env.MYCELIUM_INTERNAL_API_URL) return process.env.MYCELIUM_INTERNAL_API_URL;
  try {
    const text = readFileSync(join(homedir(), ".mycelium", "config.toml"), "utf8");
    const m =
      text.match(/\[server\][\s\S]*?\n\s*api_url\s*=\s*"([^"]+)"/) ??
      text.match(/^\s*api_url\s*=\s*"([^"]+)"/m);
    if (m) return m[1];
  } catch {
    /* fall through */
  }
  return "http://localhost:8000";
}

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ name: string }> },
) {
  const { name } = await params;
  const upstream = `${getBackendUrl()}/api/rooms/${encodeURIComponent(name)}/messages/stream`;

  const res = await fetch(upstream, {
    headers: { Accept: "text/event-stream", "Cache-Control": "no-cache" },
  });

  if (!res.ok || !res.body) {
    return new Response("upstream SSE unavailable", { status: 502 });
  }

  return new Response(res.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
