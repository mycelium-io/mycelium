// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

/**
 * All HTTP / gateway RPC — env access lives in mycelium-env.ts.
 */

import { getApiUrl } from "./mycelium-env.js";

export type SubagentRuntime = {
  run: (params: {
    sessionKey: string;
    message: string;
    deliver?: boolean;
    idempotencyKey?: string;
  }) => Promise<{ runId: string }>;
};

export async function apiPost(
  path: string,
  body: unknown,
  log: { warn: (s: string) => void }
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
  log: { warn: (s: string) => void }
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

/** SSE stream for coordination ticks (caller consumes body). */
export async function fetchAgentEventStream(
  handle: string,
  signal: AbortSignal
): Promise<Response> {
  const base = getApiUrl();
  return fetch(`${base}/agents/${encodeURIComponent(handle)}/stream`, {
    headers: { Accept: "text/event-stream" },
    signal,
  });
}

export function wakeAgent(
  params: {
    sessionKey: string;
    message: string;
    idempotencyKey: string;
  },
  subagent: SubagentRuntime,
  log: { info: (s: string) => void; warn: (s: string) => void },
  handle: string
): void {
  void subagent.run({
    sessionKey: params.sessionKey,
    message: params.message,
    deliver: true,
    idempotencyKey: params.idempotencyKey,
  }).then(() => {
    log.info(`[mycelium] wake dispatched for ${handle}`);
  }).catch((err: unknown) => {
    log.warn(`[mycelium] wake failed for ${handle}: ${err}`);
  });
}
