// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors
import { installChannel } from "./channel/index.js";
import { loadMyceliumConfig, readChannelConfigs } from "./config.js";
import { installSession } from "./session/index.js";
export function register(api) {
    const log = api.logger;
    loadMyceliumConfig();
    const channelCfgs = readChannelConfigs(api.config);
    // Session lifecycle is room-agnostic — it only needs backendUrl. Pass the
    // first config (or null) the same way the single-room code always did.
    installSession(api, channelCfgs[0] ?? null, log);
    if (channelCfgs.length > 0) {
        for (const c of channelCfgs) {
            log.info(`[mycelium-room] configured — room: ${c.room}, agents: [${c.agents.join(", ")}], backend: ${c.backendUrl}, requireMention: ${c.requireMention}`);
        }
        installChannel(api, channelCfgs, log);
    }
    else {
        log.warn("[mycelium-room] channel inactive — set channels.mycelium-room in openclaw.json to enable addressed messaging");
    }
}
