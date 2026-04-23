// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Cisco Systems, Inc. and its affiliates

/**
 * mycelium — OpenClaw plugin entry point.
 *
 * Thin wrapper around the register function in src/register.ts. All behavior
 * is decomposed into concern modules under src/:
 *
 *   src/channel/         — room SSE subscription + addressed agent dispatch
 *   src/session/         — session lifecycle + per-turn context injection
 *   src/knowledge/       — message_sent → knowledge graph ingest
 *   src/config.ts        — env + openclaw.json config loading
 *   src/http.ts          — apiGet/apiPost/health
 *   src/session-key.ts   — sessionKey builder matching OpenClaw routing format
 *   src/instructions.ts  — MYCELIUM_INSTRUCTIONS system prompt constant
 *
 * See src/register.ts for the full wiring.
 */

import { register } from "./src/register.js";

const plugin = {
  id: "mycelium",
  name: "Mycelium Adapter",
  description:
    "Bridges OpenClaw agents to the Mycelium coordination backend. Covers session lifecycle, pre-turn context injection, addressed messaging via the mycelium-room channel, and knowledge graph ingest.",
  register,
};

export default plugin;
