// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { getBackendUrl } from "@/lib/backend";
import { bearer } from "@/lib/session";
import { handleMock, isMockMode } from "@/mocks";

/**
 * Catch-all proxy for `/api/*` → the backend, resolved at REQUEST time.
 *
 * Replaces the old next.config rewrite whose destination was frozen at build
 * time (to localhost:8000), ignoring the runtime MYCELIUM_INTERNAL_API_URL and
 * breaking the Dockerized UI. The more-specific SSE route handler
 * (rooms/[name]/messages/stream) still takes precedence for the stream
 * endpoint; everything else flows through here.
 */
export const dynamic = "force-dynamic";

// Headers that must not be forwarded verbatim across the proxy hop.
const STRIP_REQUEST = ["host", "connection", "keep-alive", "transfer-encoding", "upgrade", "content-length"];
const STRIP_RESPONSE = ["connection", "keep-alive", "transfer-encoding", "upgrade", "content-length", "content-encoding"];

async function proxy(req: Request): Promise<Response> {
  // Fake-backend mode: serve fixtures instead of proxying. A route we haven't
  // mocked returns null and falls through to the real backend below.
  if (isMockMode()) {
    const mocked = await handleMock(req);
    if (mocked) return mocked;
  }

  const backend = getBackendUrl();
  const { pathname, search } = new URL(req.url);
  // The backend serves health at the root (`/health`), while everything else it
  // exposes is under `/api`. Map the proxied `/api/health` onto the root path so
  // the health/fabric views can read it through the same proxy.
  const backendPath = pathname === "/api/health" ? "/health" : pathname;
  const target = `${backend}${backendPath}${search}`;

  const headers = new Headers(req.headers);
  for (const h of STRIP_REQUEST) headers.delete(h);
  // Ask upstream for plain bytes so we can stream the response straight through
  // without a content-encoding/content-length mismatch.
  headers.delete("accept-encoding");
  // Attach the signed-in user's bearer (refreshing it if near expiry). Returns
  // null when there's no session — gate off or signed out — so the header stays
  // absent and the proxy behaves exactly as it did before OIDC existed.
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
    res = await fetch(target, init);
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
