// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Tests for the per-agent dispatch chain. Behavioural contract:
 *   - Same-agent dispatches run strictly serially.
 *   - Different-agent dispatches run concurrently.
 *   - Errors in one dispatch don't poison subsequent dispatches.
 *   - Timeout releases the chain so a hung dispatch can't wedge the agent
 *     permanently.
 */

import { afterEach, describe, expect, it } from "vitest";

import {
  DispatchTimeoutError,
  _chainDepthForTest,
  _resetChainsForTest,
  enqueueDispatch,
} from "../src/channel/dispatch-chain.js";

const makeLogger = () => {
  const lines: { level: "info" | "warn"; msg: string }[] = [];
  return {
    info: (msg: string) => lines.push({ level: "info", msg }),
    warn: (msg: string) => lines.push({ level: "warn", msg }),
    lines,
  };
};

afterEach(() => {
  _resetChainsForTest();
});

describe("enqueueDispatch — same-agent serialization", () => {
  it("runs same-agent dispatches strictly serially", async () => {
    const order: string[] = [];
    const release: Array<() => void> = [];
    const makeTask = (label: string) => async () => {
      order.push(`${label}-start`);
      await new Promise<void>((res) => release.push(res));
      order.push(`${label}-end`);
    };

    const p1 = enqueueDispatch("alpha", makeTask("a"));
    const p2 = enqueueDispatch("alpha", makeTask("b"));
    const p3 = enqueueDispatch("alpha", makeTask("c"));

    // Yield so the first task can enter.
    await new Promise((res) => setTimeout(res, 0));
    expect(order).toEqual(["a-start"]);

    // Release tasks one at a time and assert nothing interleaves.
    release[0]!();
    await new Promise((res) => setTimeout(res, 0));
    expect(order).toEqual(["a-start", "a-end", "b-start"]);

    release[1]!();
    await new Promise((res) => setTimeout(res, 0));
    expect(order).toEqual(["a-start", "a-end", "b-start", "b-end", "c-start"]);

    release[2]!();
    await Promise.all([p1, p2, p3]);
    expect(order).toEqual([
      "a-start",
      "a-end",
      "b-start",
      "b-end",
      "c-start",
      "c-end",
    ]);
  });

  it("logs chain depth >1 at info level", async () => {
    const log = makeLogger();
    let allow = false;
    const waitForAllow = async () => {
      while (!allow) await new Promise((res) => setTimeout(res, 1));
    };

    const p1 = enqueueDispatch("alpha", waitForAllow, { log });
    const p2 = enqueueDispatch("alpha", waitForAllow, { log });
    const p3 = enqueueDispatch("alpha", waitForAllow, { log });

    const depthLogs = log.lines.filter((l) => l.msg.includes("chain depth"));
    expect(depthLogs).toHaveLength(2); // depths 2 and 3 logged; depth 1 is not
    expect(depthLogs[0]!.msg).toContain("depth=2");
    expect(depthLogs[1]!.msg).toContain("depth=3");

    allow = true;
    await Promise.all([p1, p2, p3]);
  });
});

describe("enqueueDispatch — cross-agent concurrency", () => {
  it("runs different-agent dispatches in parallel", async () => {
    const order: string[] = [];
    let alphaReleased = false;
    const taskAlpha = async () => {
      order.push("alpha-start");
      while (!alphaReleased) {
        await new Promise((res) => setTimeout(res, 1));
      }
      order.push("alpha-end");
    };
    const taskBeta = async () => {
      order.push("beta-start");
      order.push("beta-end");
    };

    const pa = enqueueDispatch("alpha", taskAlpha);
    const pb = enqueueDispatch("beta", taskBeta);

    // beta should be able to start + finish while alpha is still running
    await pb;
    expect(order).toEqual(["alpha-start", "beta-start", "beta-end"]);

    alphaReleased = true;
    await pa;
    expect(order).toEqual([
      "alpha-start",
      "beta-start",
      "beta-end",
      "alpha-end",
    ]);
  });
});

describe("enqueueDispatch — error containment", () => {
  it("does not poison the chain when a prior dispatch throws", async () => {
    const log = makeLogger();
    const order: string[] = [];

    const p1 = enqueueDispatch(
      "alpha",
      async () => {
        order.push("a-start");
        throw new Error("kaboom");
      },
      { log },
    );
    const p2 = enqueueDispatch(
      "alpha",
      async () => {
        order.push("b-start");
        order.push("b-end");
      },
      { log },
    );

    await Promise.all([p1, p2]);
    expect(order).toEqual(["a-start", "b-start", "b-end"]);
    expect(log.lines.some((l) => l.level === "warn" && /chain error/.test(l.msg))).toBe(
      true,
    );
  });

  it("never rejects the returned promise (safe for fire-and-forget)", async () => {
    // enqueueDispatch returns a promise that resolves whether or not the
    // underlying fn threw — callers `void` the return value and unhandled
    // rejections would crash the gateway. Assert: the promise resolves
    // with undefined even when fn throws.
    const result = await enqueueDispatch("alpha", async () => {
      throw new Error("nope");
    });
    expect(result).toBeUndefined();
  });
});

describe("enqueueDispatch — timeout", () => {
  it("releases the chain when a dispatch exceeds the timeout", async () => {
    const log = makeLogger();
    let bSawTimeoutLog = false;

    // Task a hangs forever; task b should still run after the timeout fires.
    const p1 = enqueueDispatch("alpha", () => new Promise<void>(() => {}), {
      timeoutMs: 50,
      log,
    });
    const p2 = enqueueDispatch(
      "alpha",
      async () => {
        bSawTimeoutLog = log.lines.some(
          (l) => l.level === "warn" && l.msg.includes("timed out"),
        );
      },
      { timeoutMs: 50, log },
    );

    await p1; // resolves after timeout
    await p2;
    expect(bSawTimeoutLog).toBe(true);
  });

  it("emits a DispatchTimeoutError shape in the warn log", async () => {
    const log = makeLogger();
    await enqueueDispatch("alpha", () => new Promise<void>(() => {}), {
      timeoutMs: 30,
      log,
    });
    const warns = log.lines.filter((l) => l.level === "warn");
    expect(warns.some((w) => w.msg.includes("alpha") && w.msg.includes("30ms"))).toBe(
      true,
    );
  });
});

describe("enqueueDispatch — internal accounting", () => {
  it("returns chain depth to 0 after all dispatches settle", async () => {
    let allow = false;
    const waitForAllow = async () => {
      while (!allow) await new Promise((res) => setTimeout(res, 1));
    };
    const p1 = enqueueDispatch("alpha", waitForAllow);
    const p2 = enqueueDispatch("alpha", waitForAllow);
    expect(_chainDepthForTest("alpha")).toBe(2);
    allow = true;
    await Promise.all([p1, p2]);
    expect(_chainDepthForTest("alpha")).toBe(0);
  });
});

describe("DispatchTimeoutError", () => {
  it("preserves agentId and timeoutMs", () => {
    const err = new DispatchTimeoutError("alpha", 5000);
    expect(err.agentId).toBe("alpha");
    expect(err.timeoutMs).toBe(5000);
    expect(err.name).toBe("DispatchTimeoutError");
  });
});
