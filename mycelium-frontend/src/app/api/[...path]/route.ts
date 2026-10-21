// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { getBackendUrl, upstreamHeaders, upstreamUrl } from "@/lib/backend";
import { HEALTH_PATH, fetchHealth } from "@/lib/hub-health";
import { bearer } from "@/lib/session";
import { TOKEN_HEADER } from "@/lib/ui-guard";
import { MOCK_HEADER, handleMock, isMockMode } from "@/mocks";

/**
 * Catch-all proxy for `/api/*` → the backend, resolved at REQUEST time.
 * The more-specific SSE route handler (rooms/[name]/messages/stream) takes precedence.
 */
export const dynamic = "force-dynamic";

// Headers that must not be passed back verbatim across the proxy hop.
const STRIP_RESPONSE = ["connection", "keep-alive", "transfer-encoding", "upgrade", "content-length", "content-encoding"];

async function proxy(req: Request): Promise<Response> {
  // Fake-backend mode: serve fixtures instead of proxying. A route we haven't
  // mocked returns null and falls through to the real backend below.
  if (isMockMode()) {
    const mocked = await handleMock(req);
    if (mocked) {
      // Says so on the wire, so a tool attaching to a running dev server can
      // tell a mock app from one in front of a real hub.
      mocked.headers.set(MOCK_HEADER, "1");
      return mocked;
    }
  }

  const backend = getBackendUrl();
  const target = upstreamUrl(backend, req.url);

  const headers = upstreamHeaders(req);
  // The app's own proof stays here: the hub never sees it, so it never lands
  // in the hub's log, on this machine or another (`lib/ui-guard.ts`).
  headers.delete(TOKEN_HEADER);
  // Ask upstream for plain bytes so we can stream the response straight through
  // without a content-encoding/content-length mismatch.
  headers.delete("accept-encoding");
  // Attach the signed-in user's bearer, refreshing it if near expiry. Returns
  // null when there's no session — gate off or signed out — so the header
  // stays absent.
  const token = await bearer();
  if (token) headers.set("authorization", `Bearer ${token}`);

  const init: RequestInit = {
    method: req.method,
    headers,
    cache: "no-store",
    redirect: "manual",
  };
  if (req.method !== "GET" && req.method !== "HEAD") {
    init.body = await req.arrayBuffer();
  }

  let res: Response;
  try {
    res = new URL(req.url).pathname === HEALTH_PATH ? await fetchHealth(init, backend) : await fetch(target, init);
  } catch {
    return Response.json(
      { detail: `Backend unreachable at ${backend}` },
      { status: 502 },
    );
  }

  const respHeaders = new Headers(res.headers);
  for (const h of STRIP_RESPONSE) respHeaders.delete(h);

  return new Response(res.body, {
    status: res.status,
    statusText: res.statusText,
    headers: respHeaders,
  });
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
export const HEAD = proxy;
export const OPTIONS = proxy;
