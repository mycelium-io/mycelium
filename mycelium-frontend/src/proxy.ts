// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { NextResponse, type NextRequest } from "next/server";
import { guardApi, hostAllowed } from "@/lib/ui-guard";

/**
 * What every request must show before this server does anything with it
 * (`lib/ui-guard.ts`). Pages: a name this server serves, so a page that
 * rebinds its own name to this machine never gets one. `/api`: that, plus its
 * own origin, a JSON body, and proof it comes from this app's own pages.
 */
export function proxy(req: NextRequest): NextResponse | Response {
  if (/^\/api\//.test(req.nextUrl.pathname)) {
    return guardApi(req) ?? NextResponse.next();
  }
  if (!hostAllowed(req.headers.get("host"))) {
    return new NextResponse("This server doesn't answer to that name.", { status: 421 });
  }
  return NextResponse.next();
}

// Static files (the app's own scripts, styles, images and fonts) hold nothing
// of the person's, and Next's image optimizer fetches public images from this
// server itself, so they're left out.
export const config = {
  matcher: [
    "/((?!_next/static|_next/image|.*\\.(?:png|jpe?g|gif|svg|ico|webp|avif|woff2?|ttf|css|js|map|txt)$).*)",
  ],
};
