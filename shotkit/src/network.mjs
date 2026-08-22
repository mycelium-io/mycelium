// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * What the page is allowed to reach.
 *
 * A local app is fast; the CDNs it references are not necessarily reachable.
 * The frontend links Google Fonts, and behind a proxy that cannot reach them
 * each navigation spent about thirteen seconds waiting before giving up — two
 * orders of magnitude more than the capture itself. `--offline` turns that wait
 * into an instant, deterministic failure, and the app renders with its fallback
 * fonts.
 *
 * This is done with Chromium's own host-resolver rules rather than Playwright's
 * request interception, which is the more obvious tool. Interception is a CDP
 * feature and it silently stops completing requests when the driver and the
 * browser build disagree — a mismatch this tool deliberately tolerates, since it
 * runs against whatever Chromium the host already has. A launch flag has no such
 * coupling: it is read by the browser, and either the browser starts or it does
 * not.
 *
 * The cost is that the policy belongs to a browser process, not a page, so the
 * engine keeps one browser per distinct policy.
 */

/**
 * @typedef {object} NetworkPolicy
 * @property {boolean} [offline] resolve nothing but localhost
 * @property {string[]} [block] additional hosts to fail immediately
 */

/** A stable key for one policy, used to pick the browser that enforces it. */
export function policyKey(policy = {}) {
  const blocked = [...(policy.block ?? [])].sort();
  if (!policy.offline && blocked.length === 0) return "open";
  return `${policy.offline ? "offline" : "open"}|${blocked.join(",")}`;
}

/**
 * Launch args implementing a policy.
 *
 * `~NOTFOUND` makes the resolver fail the lookup outright, so a blocked request
 * ends in milliseconds instead of a connect timeout.
 *
 * Only `localhost` is excluded, and deliberately: EXCLUDE takes hostname
 * patterns, and adding an IP literal such as `EXCLUDE 127.0.0.1` makes Chromium
 * reject the entire rule string *silently* — every rule stops applying and the
 * slow fetches quietly come back. The loopback address needs no exclusion
 * anyway, since a numeric host never reaches the resolver.
 * @param {NetworkPolicy} policy
 * @returns {string[]}
 */
export function policyArgs(policy = {}) {
  const rules = (policy.block ?? []).map((host) => `MAP ${host} ~NOTFOUND`);
  if (policy.offline) rules.push("MAP * ~NOTFOUND", "EXCLUDE localhost");
  if (rules.length === 0) return [];
  return [`--host-resolver-rules=${rules.join(", ")}`];
}

/** Human-readable summary for `--json` and the status line. */
export function describePolicy(policy = {}) {
  if (policy.offline) return "offline (localhost only)";
  if (policy.block?.length) return `blocking ${policy.block.join(", ")}`;
  return "open";
}
