// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Fake-backend mode for the UI.
 *
 * With `MYCELIUM_UI_MOCK=1`, the Next route handlers serve fixtures instead of
 * proxying to a real backend — so the whole UI renders populated / in-progress /
 * empty states with no SLIM node, no LLM, and no backend server. This is the
 * frontend analogue of the backend/CLI fake stacks: one command (`pnpm dev:mock`)
 * to reach any state, for design and visual-regression work.
 *
 * The toggle is read per-request (server-side) so nothing is baked into the
 * build. Import `handleMock` / `mockStream` only from server code (route
 * handlers); the fixtures never reach the client bundle.
 */

export { handleMock } from "./handlers";
export { mockStream } from "./stream";

export function isMockMode(): boolean {
  const v = (process.env.MYCELIUM_UI_MOCK ?? "").toLowerCase();
  return v === "1" || v === "true" || v === "yes";
}
