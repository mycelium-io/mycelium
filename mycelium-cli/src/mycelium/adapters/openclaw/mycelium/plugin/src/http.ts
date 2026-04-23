// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Cisco Systems, Inc. and its affiliates

/**
 * HTTP helpers for talking to the Mycelium backend.
 *
 * Env access lives in config.ts. No subprocess orchestration, no wakeAgent —
 * agent dispatch happens in-process via runtime.channel.reply (see channel/dispatch.ts).
 */

import { getApiUrl } from "./config.js";

export async function apiPost(
  path: string,
  body: unknown,
  log: { warn: (s: string) => void },
): Promise<boolean> {
  const base = getApiUrl();
  try {
    const res = await fetch(`${base}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      log.warn(`[mycelium] POST ${path} → ${res.status}`);
      return false;
    }
    return true;
  } catch (e) {
    log.warn(`[mycelium] POST ${path} error: ${e}`);
    return false;
  }
}

export async function apiGet(
  path: string,
  log: { warn: (s: string) => void },
): Promise<unknown> {
  const base = getApiUrl();
  try {
    const res = await fetch(`${base}${path}`);
    if (!res.ok) return null;
    return await res.json();
  } catch (e) {
    log.warn(`[mycelium] GET ${path} error: ${e}`);
    return null;
  }
}

export async function fetchBackendHealth(): Promise<Response> {
  return fetch(`${getApiUrl()}/health`);
}
