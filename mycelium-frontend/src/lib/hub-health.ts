// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { getBackendUrl } from "./backend";

/** The health path as the page asks for it, and as a hub that serves its own pages answers it. */
export const HEALTH_PATH = "/api/health";

/**
 * Fetch the hub's health. A backend answers it at its root (`/health`); a hub
 * that serves its own pages (what the desktop app reaches in client mode)
 * answers it under `/api`, and its root `/health` is a missing page. Every
 * server-side reader of the hub's health goes through here, so none of them
 * can take that missing page for a hub with no sign-in. Throws when the hub
 * can't be reached, like `fetch`.
 *
 * Only import this from server code (route handlers).
 */
export async function fetchHealth(
  init: RequestInit = { cache: "no-store" },
  backend: string = getBackendUrl(),
): Promise<Response> {
  const res = await fetch(`${backend}/health`, init);
  return res.status === 404 ? fetch(`${backend}${HEALTH_PATH}`, init) : res;
}
