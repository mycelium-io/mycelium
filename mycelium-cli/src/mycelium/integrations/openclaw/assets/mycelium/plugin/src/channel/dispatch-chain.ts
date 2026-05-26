// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

/**
 * Per-agent dispatch chain — guarantees that only one `dispatchToAgent` call
 * is in flight per agentId at a time.
 *
 * Why this exists. The channel plugin invokes `dispatchToAgent` (which calls
 * `runtime.channel.reply.dispatchReplyWithBufferedBlockDispatcher`) as
 * fire-and-forget on every routed inbound message. In production traffic
 * the same agent can legitimately receive multiple messages while its
 * previous LLM turn is still in flight — a coordination_tick for the next
 * round, the coordination_consensus that closes the session, an
 * @-mention from another agent, etc. Without serialization at our layer,
 * openclaw's lane queue sees q>1 for the same session-key.
 *
 * The lane is *supposed* to serialize, but we have observed wedges
 * (openclaw/openclaw#48488) where a queued task never advances. Whether
 * those are caused by openclaw bugs or by something we trigger, serializing
 * at our layer:
 *
 *   - keeps openclaw's lane depth at ≤ 1 for our channel, narrowing the
 *     surface where the upstream bug can fire;
 *   - has zero observable effect when openclaw's lane is healthy (each
 *     dispatch already had to wait for the previous LLM turn for the agent
 *     to be useful — running them concurrently never produced sensible
 *     behaviour);
 *   - is purely local to this file.
 *
 * The chain has a per-dispatch timeout so a hung promise can never wedge
 * an agent permanently — that would be the same failure shape this guard
 * is trying to escape. On timeout we release the chain with a warn log;
 * the in-flight task is *not* cancelled (we can't cancel an LLM turn
 * mid-flight) but subsequent dispatches for that agent are no longer
 * blocked behind it.
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
