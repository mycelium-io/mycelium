// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { getBackendUrl } from "@/lib/backend";
import { isMockMode } from "@/mocks";

const SSE_HEADERS = {
  "Content-Type": "text/event-stream",
  "Cache-Control": "no-cache, no-transform",
  Connection: "keep-alive",
  "X-Accel-Buffering": "no",
};

export async function GET() {
  // Fake-backend mode has no live room churn: hold an idle keep-alive stream
  // open so the client's EventSource connects cleanly and never errors.
  if (isMockMode()) {
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode("event: ping\ndata: {}\n\n"));
      },
    });
    return new Response(stream, { headers: SSE_HEADERS });
  }

  const upstream = `${getBackendUrl()}/api/events/stream`;
  const res = await fetch(upstream, {
    headers: { Accept: "text/event-stream", "Cache-Control": "no-cache" },
    cache: "no-store",
  });

  if (!res.ok || !res.body) {
    return new Response("upstream SSE unavailable", { status: 502 });
  }

  // Pipe through a TransformStream so each chunk flushes immediately rather
  // than waiting for Next.js to decide when to flush (mirrors the room stream).
  const { readable, writable } = new TransformStream();
  res.body.pipeTo(writable).catch(() => {/* client disconnect */});

  return new Response(readable, { headers: SSE_HEADERS });
}
