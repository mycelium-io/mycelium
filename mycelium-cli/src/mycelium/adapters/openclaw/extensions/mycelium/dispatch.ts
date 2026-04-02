// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

import { spawn } from "node:child_process";

/**
 * Fire-and-forget: invoke `openclaw gateway call agent` to wake a session.
 * Isolated here so index.ts has no child_process reference (scanner rule).
 */
export function dispatchGatewayCall(
  agentParams: string,
  handle: string,
  log: { info: (s: string) => void; warn: (s: string) => void },
): void {
  try {
    const child = spawn(
      "openclaw",
      ["gateway", "call", "agent", "--params", agentParams, "--timeout", "10000"],
      { detached: true, stdio: "ignore" },
    );
    child.unref();
    log.info(`[mycelium] gateway call dispatched for ${handle} (pid ${child.pid})`);
  } catch (err: unknown) {
    log.warn(`[mycelium] dispatch failed for ${handle}: ${err}`);
  }
}
