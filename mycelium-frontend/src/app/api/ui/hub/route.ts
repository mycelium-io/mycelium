// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// Which hub this UI talks to, when the page's own address doesn't say: the
// desktop app's UI joined to a hub elsewhere (client mode) runs on this
// machine, so its pages are on 127.0.0.1 while the hub is not. Answers that
// hub's address, or null when the hub is on this machine and the page's
// origin already names it. Read by `lib/hub-address.ts`.

import { NextResponse } from "next/server";
import { getBackendUrl } from "@/lib/backend";
import { WORKSHOP_HUB_URL } from "@/mocks/workshop-room";

export const dynamic = "force-dynamic";

const LOOPBACK = /^(127\.0\.0\.1|localhost|\[::1\])$/;

export function GET(): Response {
  // The workshop's mock is a team's hub, not one on this computer.
  if (process.env.MYCELIUM_UI_MOCK === "1" && /^workshop:/i.test(process.env.MYCELIUM_UI_MOCK_SCENARIO ?? "")) {
    return NextResponse.json({ url: WORKSHOP_HUB_URL });
  }
  let url: URL;
  try {
    url = new URL(getBackendUrl());
  } catch {
    return NextResponse.json({ url: null });
  }
  return NextResponse.json({ url: LOOPBACK.test(url.hostname) ? null : url.origin });
}
