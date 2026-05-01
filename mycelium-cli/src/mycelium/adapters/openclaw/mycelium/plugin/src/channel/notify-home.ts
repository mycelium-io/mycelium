// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

/**
 * Cross-channel return-trip notification.
 *
 * When a coordination negotiation reaches consensus (or times out) in a
 * mycelium-room session sub-room, the agents that participated may have a
 * "home" session elsewhere — e.g., a Matrix DM or Discord channel where
 * their human asked them to coordinate. This module delivers a one-shot
 * summary back to that home session via OpenClaw's outbound adapter API,
 * so the user sees the result in their own chat rather than having to come
 * find it in mycelium.
 *
 * The home address is captured at the moment the agent joins the negotiation
 * (see ./return-address.ts) — frozen there to avoid drift between join and
 * consensus.
 *
 * Best-effort only: no stashed address ⇒ skip silently. Outbound failure ⇒
 * log and continue.
 */

import { CHANNEL_ID, type ChannelConfig } from "../config.js";
import {
  clearReturnAddresses,
  lookupReturnAddress,
} from "./return-address.js";

type Logger = { info: (s: string) => void; warn: (s: string) => void };

export async function executeNotifyHome(
  runtime: any,
  cfg: ChannelConfig,
  sessionRoom: string,
  agentIds: string[],
  summary: string,
  log: Logger,
): Promise<void> {
  let openclawConfig: any;
  try {
    openclawConfig = runtime.config.loadConfig();
  } catch (err: any) {
    log.warn(
      `[${CHANNEL_ID}] notify-home: failed to load openclaw config — ${err?.message ?? err}`,
    );
    return;
  }

  const loadAdapter = runtime?.channel?.outbound?.loadAdapter;
  if (typeof loadAdapter !== "function") {
    log.warn(
      `[${CHANNEL_ID}] notify-home: runtime.channel.outbound.loadAdapter not available — return-trip disabled`,
    );
    return;
  }

  for (const agentId of agentIds) {
    const addr = lookupReturnAddress(sessionRoom, agentId);
    if (!addr) {
      log.info(
        `[${CHANNEL_ID}] notify-home: no return address for ${agentId} in ${sessionRoom} — skipping`,
      );
      continue;
    }

    let adapter: any;
    try {
      adapter = await loadAdapter(addr.channelName);
    } catch (err: any) {
      log.warn(
        `[${CHANNEL_ID}] notify-home: loadAdapter(${addr.channelName}) failed — ${err?.message ?? err}`,
      );
      continue;
    }
    if (!adapter || typeof adapter.sendText !== "function") {
      log.warn(
        `[${CHANNEL_ID}] notify-home: no sendText for channel ${addr.channelName} — skipping ${agentId}`,
      );
      continue;
    }

    const text = `[Mycelium return trip — ${cfg.room}]\n\n${summary}`;
    try {
      await adapter.sendText({
        cfg: openclawConfig,
        to: addr.to,
        text,
        accountId: addr.accountId,
      });
      log.info(
        `[${CHANNEL_ID}] notify-home → ${agentId} on ${addr.channelName}:${addr.to}`,
      );
    } catch (err: any) {
      log.warn(
        `[${CHANNEL_ID}] notify-home failed for ${agentId} on ${addr.channelName}:${addr.to} — ${err?.message ?? err}`,
      );
    }
  }

  // Negotiation is over — drop the stash for this session sub-room.
  clearReturnAddresses(sessionRoom);
}
