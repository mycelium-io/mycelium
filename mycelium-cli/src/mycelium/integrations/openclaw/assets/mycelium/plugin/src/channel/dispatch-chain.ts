// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Per-agent dispatch chain — serializes `dispatchToAgent` calls per agentId,
 * narrowing the surface of an observed openclaw lane wedge (openclaw/openclaw#48488).
 * A per-dispatch timeout releases the chain (with a warn log) if a promise hangs,
 * so one stuck dispatch can't permanently block an agent's later ones.
 */

export type Logger = {
  info: (s: string) => void;
  warn: (s: string) => void;
};

export const DEFAULT_DISPATCH_TIMEOUT_MS = 120_000; // 2 minutes

/** Internal state. Exported via `_resetChainsForTest` for vitest. */
const _chains = new Map<string, Promise<unknown>>();
const _depth = new Map<string, number>();

export class DispatchTimeoutError extends Error {
  constructor(
    public agentId: string,
    public timeoutMs: number,
  ) {
    super(`dispatch timeout after ${timeoutMs}ms for ${agentId}`);
    this.name = "DispatchTimeoutError";
  }
}

function _withTimeout<T>(
  promise: Promise<T>,
  ms: number,
  agentId: string,
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const handle = setTimeout(() => {
      reject(new DispatchTimeoutError(agentId, ms));
    }, ms);
    // Don't keep the event loop alive just for the timer.
    (handle as { unref?: () => void }).unref?.();
    promise.then(
      (value) => {
        clearTimeout(handle);
        resolve(value);
      },
      (err) => {
        clearTimeout(handle);
        reject(err);
      },
    );
  });
}

export interface EnqueueOpts {
  timeoutMs?: number;
  log?: Logger;
}

/**
 * Queue `fn` behind any in-flight or queued dispatch for `agentId`.
 *
 * Returns a promise that resolves when `fn` settles (or when the timeout
 * fires). The promise never rejects — internal errors are logged so the
 * fire-and-forget caller can `void` the return value without leaking
 * unhandledrejection events.
 */
export function enqueueDispatch(
  agentId: string,
  fn: () => Promise<void>,
  opts: EnqueueOpts = {},
): Promise<void> {
  const timeoutMs = opts.timeoutMs ?? DEFAULT_DISPATCH_TIMEOUT_MS;
  const log = opts.log;

  const newDepth = (_depth.get(agentId) ?? 0) + 1;
  _depth.set(agentId, newDepth);
  if (newDepth > 1 && log) {
    log.info(
      `[mycelium-room] dispatch queued for ${agentId} (chain depth=${newDepth})`,
    );
  }

  const prev = _chains.get(agentId) ?? Promise.resolve();
  // Swallow prior errors so a failed predecessor never poisons the chain.
  const next: Promise<void> = prev.catch(() => {}).then(async () => {
    try {
      await _withTimeout(fn(), timeoutMs, agentId);
    } catch (err) {
      if (err instanceof DispatchTimeoutError) {
        log?.warn(
          `[mycelium-room] dispatch timed out after ${timeoutMs}ms for ${agentId} — releasing chain (in-flight task not cancellable)`,
        );
      } else {
        log?.warn(
          `[mycelium-room] dispatch chain error for ${agentId}: ${err instanceof Error ? err.message : String(err)}`,
        );
      }
    } finally {
      const remaining = (_depth.get(agentId) ?? 1) - 1;
      if (remaining <= 0) {
        _depth.delete(agentId);
        // Only delete the chain entry if we're still the tail. A later
        // enqueue between settle and finally would have replaced it.
        if (_chains.get(agentId) === next) {
          _chains.delete(agentId);
        }
      } else {
        _depth.set(agentId, remaining);
      }
    }
  });
  _chains.set(agentId, next);
  return next;
}

/** Test-only: reset internal state between vitest cases. */
export function _resetChainsForTest(): void {
  _chains.clear();
  _depth.clear();
}

/** Test-only: read current chain depth for an agent. */
export function _chainDepthForTest(agentId: string): number {
  return _depth.get(agentId) ?? 0;
}
