// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

/**
 * Unified plugin register function.
 *
 * Wires two concerns into the OpenClawPluginApi:
 *
 *   1. Session lifecycle  — always installed (tracks session_start/end,
 *                           injects MYCELIUM_INSTRUCTIONS via before_agent_start)
 *   2. Channel            — installed iff channels.mycelium-room is configured
 *                           (room SSE, addressed dispatch, coordination ticks)
 *
 * Each concern is a self-contained install* function that takes the api and
 * registers its own hooks. register() is purely the conductor.
 *
 * Knowledge extraction (KXP) used to live here as a third concern that
 * silently shipped every message_sent / Stop event to the backend. That
 * path is gone. KXP now fires only on deliberate room artifacts —
 * channel-message POST and ``mycelium memory set`` — wired in the backend.
 */

import type { OpenClawPluginApi } from "openclaw/plugin-sdk";

import { installChannel } from "./channel/index.js";
import { loadMyceliumConfig, readChannelConfigs } from "./config.js";
import { installSession } from "./session/index.js";

export function register(api: OpenClawPluginApi): void {
  const log = api.logger;

  loadMyceliumConfig();
  const channelCfgs = readChannelConfigs(api.config);

  // Session lifecycle is room-agnostic — it only needs backendUrl. Pass the
  // first config (or null) the same way the single-room code always did.
  installSession(api, channelCfgs[0] ?? null, log);

  if (channelCfgs.length > 0) {
    for (const c of channelCfgs) {
      log.info(
        `[mycelium-room] configured — room: ${c.room}, agents: [${c.agents.join(", ")}], backend: ${c.backendUrl}, requireMention: ${c.requireMention}`,
      );
    }
    installChannel(api, channelCfgs, log);
  } else {
    log.warn(
      "[mycelium-room] channel inactive — set channels.mycelium-room in openclaw.json to enable addressed messaging",
    );
  }
}
