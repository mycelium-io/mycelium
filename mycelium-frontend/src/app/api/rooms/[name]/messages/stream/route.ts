// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { getBackendUrl } from "@/lib/backend";
import { isMockMode, mockStream } from "@/mocks";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ name: string }> },
) {
  const { name } = await params;
  // Fake-backend mode: replay a scripted live negotiation instead of proxying.
  if (isMockMode()) return mockStream(name);

  const upstream = `${getBackendUrl()}/api/rooms/${encodeURIComponent(name)}/messages/stream`;

  const res = await fetch(upstream, {
    headers: { Accept: "text/event-stream", "Cache-Control": "no-cache" },
    // Prevent Next.js fetch cache from buffering the response
    cache: "no-store",
  });

  if (!res.ok || !res.body) {
    return new Response("upstream SSE unavailable", { status: 502 });
  }

  // Pipe through a TransformStream so each chunk is enqueued and flushed
  // immediately rather than waiting for Next.js to decide when to flush.
  const { readable, writable } = new TransformStream();
  res.body.pipeTo(writable).catch(() => {/* client disconnect */});

  return new Response(readable, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
