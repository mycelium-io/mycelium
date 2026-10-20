// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * `POST /api/client-log`: one line from the page (`lib/report-to-app.ts`),
 * written to this server's output as a single line. In the desktop app that
 * output is the app's log, which is where a page's errors can be read without
 * a console. Served here, never forwarded to the hub.
 */

const MAX_CHARS = 4_000;

export async function POST(req: Request): Promise<Response> {
  let line = "";
  try {
    const body = (await req.json()) as { line?: unknown };
    line = typeof body?.line === "string" ? body.line : "";
  } catch {
    line = "";
  }
  if (!line.trim()) return Response.json({ detail: "Nothing to log." }, { status: 400 });
  console.error(`[page] ${line.slice(0, MAX_CHARS).replace(/\r?\n/g, " | ")}`);
  return new Response(null, { status: 204 });
}
