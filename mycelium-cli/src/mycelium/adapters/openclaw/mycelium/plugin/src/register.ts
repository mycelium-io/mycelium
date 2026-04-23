// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Cisco Systems, Inc. and its affiliates

/**
 * Unified plugin register function.
 *
 * Wires three concerns into the OpenClawPluginApi:
 *
 *   1. Session lifecycle  — always installed (tracks session_start/end,
 *                           injects MYCELIUM_INSTRUCTIONS via before_agent_start)
 *   2. Channel            — installed iff channels.mycelium-room is configured
 *                           (room SSE, addressed dispatch, coordination ticks)
 *   3. Knowledge ingest   — always installed (forwards message_sent to the
 *                           knowledge graph ingest endpoint)
 *
 * Each concern is a self-contained install* function that takes the api and
 * registers its own hooks. register() is purely the conductor.
 */

import type { OpenClawPluginApi } from "openclaw/plugin-sdk";

import { installChannel } from "./channel/index.js";
import { loadMyceliumConfig, readChannelConfig } from "./config.js";
import { installKnowledgeIngest } from "./knowledge/ingest.js";
import { installSession } from "./session/index.js";

export function register(api: OpenClawPluginApi): void {
  const log = api.logger;

  loadMyceliumConfig();
  const channelCfg = readChannelConfig(api.config);

  installSession(api, channelCfg, log);
  installKnowledgeIngest(api, channelCfg, log);

  if (channelCfg) {
    log.info(
      `[mycelium-room] configured — room: ${channelCfg.room}, agents: [${channelCfg.agents.join(", ")}], backend: ${channelCfg.backendUrl}, requireMention: ${channelCfg.requireMention}`,
    );
    installChannel(api, channelCfg, log);
  } else {
    log.warn(
      "[mycelium-room] channel inactive — set channels.mycelium-room in openclaw.json to enable addressed messaging",
    );
  }
}
