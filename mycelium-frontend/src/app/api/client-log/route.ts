// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { admit, plainLine } from "@/lib/client-log";

/**
 * `POST /api/client-log`: one line from the page (`lib/report-to-app.ts`),
 * written to this server's output. In the desktop app that output is the
 * app's log, which is where a page's errors can be read without a console.
 * Served here, never forwarded to the hub.
 *
 * Only a JSON body, from this server's own pages: a page on another site
 * can't send JSON here without a preflight this route never answers. What it
 * writes, and how much, is `lib/client-log.ts`'s.
 */
export async function POST(req: Request): Promise<Response> {
  const type = (req.headers.get("content-type") ?? "").split(";")[0].trim().toLowerCase();
  if (type !== "application/json") return Response.json({ detail: "A JSON body only." }, { status: 415 });
  if (!sameSite(req)) return Response.json({ detail: "Only this app's own pages." }, { status: 403 });
  let line = "";
  try {
    const body = (await req.json()) as { line?: unknown };
    line = typeof body?.line === "string" ? plainLine(body.line) : "";
  } catch {
    line = "";
  }
  if (!line) return Response.json({ detail: "Nothing to log." }, { status: 400 });
  const out = admit(line);
  if (out === null) return Response.json({ detail: "Too many lines; this one was dropped." }, { status: 429 });
  console.error(out);
  return new Response(null, { status: 204 });
}

/** Whether the request names no other site: no `Origin`, or this server's own. */
function sameSite(req: Request): boolean {
  const origin = req.headers.get("origin");
  if (!origin) return true;
  try {
    return new URL(origin).host.toLowerCase() === (req.headers.get("host") ?? "").toLowerCase();
  } catch {
    return false;
  }
}
