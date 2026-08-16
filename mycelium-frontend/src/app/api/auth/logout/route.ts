// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// Drop the session cookie. The client reloads afterward; with the cookie gone
// the proxy forwards no token and the gate re-engages the sign-in screen.

import { NextResponse } from "next/server";
import { clearSession } from "@/lib/session";

export const dynamic = "force-dynamic";

export async function POST(): Promise<Response> {
  await clearSession();
  return NextResponse.json({ ok: true });
}
