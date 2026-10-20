// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { NextResponse, type NextRequest } from "next/server";
import { guardApi, hostAllowed, launchToken, READY_PATH, readyProof } from "@/lib/ui-guard";

/**
 * What every request must show before this server does anything with it
 * (`lib/ui-guard.ts`). Pages: a name this server serves, so a page that
 * rebinds its own name to this machine never gets one. `/api`: that, plus its
 * own origin, a JSON body, and proof it comes from this app's own pages.
 *
 * `READY_PATH` answers the supervisor, which opens the window only once the
 * server answering on the port proves it holds this launch's token.
 */
export function proxy(req: NextRequest): NextResponse | Response {
  if (/^\/api\//.test(req.nextUrl.pathname)) {
    return guardApi(req) ?? NextResponse.next();
  }
  if (!hostAllowed(req.headers.get("host"))) {
    return new NextResponse("This server doesn't answer to that name.", { status: 421 });
  }
  if (req.nextUrl.pathname === READY_PATH) {
    const token = launchToken();
    const nonce = req.nextUrl.searchParams.get("nonce") ?? "";
    if (!token || !/^[0-9a-f]{32,128}$/.test(nonce)) return new NextResponse(null, { status: 404 });
    return new NextResponse(readyProof(nonce, token), { headers: { "cache-control": "no-store" } });
  }
  return NextResponse.next();
}

// Every `/api` path, whatever it ends in (`/api/…/notes.txt` is the hub's, not a
// static file). Elsewhere, static files (the app's own scripts, styles, images
// and fonts) hold nothing of the person's, and Next's image optimizer fetches
// public images from this server itself, so they're left out.
export const config = {
  matcher: [
    "/api/:path*",
    "/((?!api/|_next/static|_next/image|.*\\.(?:png|jpe?g|gif|svg|ico|webp|avif|woff2?|ttf|css|js|map|txt)$).*)",
  ],
};
