/**
 * Mycelium channel plugin for OpenClaw.
 *
 * Agents talk to each other through Mycelium rooms instead of Discord/Slack.
 * The backend exposes REST endpoints for message send/receive and SSE for
 * real-time delivery.
 *
 * Minimal MVP — enough to prove the concept:
 * - Outbound: agent sends a message → POST to mycelium backend → stored in room
 * - Inbound: SSE from mycelium backend → delivered to agent session
 * - Group chat: all agents in a room see all messages (like a shared channel)
 */

import {
  createDefaultChannelRuntimeState,
  DEFAULT_ACCOUNT_ID,
  type ChannelPlugin,
} from "openclaw/plugin-sdk";

export type ResolvedMyceliumAccount = {
  accountId: string;
  enabled: boolean;
  configured: boolean;
  backendUrl: string;
  room: string;
  handle: string;
};

function resolveAccount(cfg: any, accountId?: string): ResolvedMyceliumAccount {
  const channels = cfg?.channels ?? {};
  const myceliumCfg = channels?.mycelium ?? {};
  const accounts = myceliumCfg?.accounts ?? {};
  const id = accountId ?? DEFAULT_ACCOUNT_ID;
  const account = accounts[id] ?? myceliumCfg;

  return {
    accountId: id,
    enabled: account.enabled !== false,
    configured: Boolean(account.backendUrl && account.room),
    backendUrl: (account.backendUrl ?? myceliumCfg.backendUrl ?? "").replace(
      /\/$/,
      ""
    ),
    room: account.room ?? myceliumCfg.room ?? "",
    handle: account.handle ?? myceliumCfg.handle ?? "",
  };
}

export const myceliumChannelPlugin: ChannelPlugin<ResolvedMyceliumAccount> = {
  id: "mycelium",
  meta: {
    id: "mycelium",
    label: "Mycelium",
    selectionLabel: "Mycelium",
    docsPath: "/channels/mycelium",
    docsLabel: "mycelium",
    blurb: "Room-based agent coordination via Mycelium",
    order: 200,
  },
  capabilities: {
    chatTypes: ["group", "direct"],
    media: false,
  },
  reload: { configPrefixes: ["channels.mycelium"] },

  config: {
    listAccountIds: (cfg) => {
      const channels = cfg?.channels ?? {};
      const myceliumCfg = (channels as any)?.mycelium ?? {};
      const accounts = myceliumCfg?.accounts;
      if (accounts && typeof accounts === "object") {
        return Object.keys(accounts);
      }
      return [DEFAULT_ACCOUNT_ID];
    },
    resolveAccount: (cfg, accountId) => resolveAccount(cfg, accountId),
    defaultAccountId: () => DEFAULT_ACCOUNT_ID,
    isConfigured: (account) => account.configured,
    describeAccount: (account) => ({
      accountId: account.accountId,
      enabled: account.enabled,
      configured: account.configured,
      backendUrl: account.backendUrl,
      room: account.room,
      handle: account.handle,
    }),
  },

  // Outbound: send agent reply to mycelium room
  outbound: {
    send: async ({ account, message }) => {
      if (!account.configured) {
        return { ok: false, error: "Mycelium channel not configured" };
      }

      const url = `${account.backendUrl}/rooms/${encodeURIComponent(account.room)}/messages`;
      try {
        const res = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            content: message.text ?? "",
            message_type: "direct",
            sender_handle: account.handle,
          }),
        });
        if (!res.ok) {
          return {
            ok: false,
            error: `Backend returned ${res.status}: ${await res.text()}`,
          };
        }
        return { ok: true };
      } catch (err: any) {
        return { ok: false, error: err?.message ?? String(err) };
      }
    },
  },

  // Gateway setup: start SSE listener for inbound messages
  gateway: {
    start: async ({ account, onInbound, log }) => {
      if (!account.configured) {
        log.warn("[mycelium-channel] not configured, skipping SSE");
        return createDefaultChannelRuntimeState();
      }

      const sseUrl = `${account.backendUrl}/rooms/${encodeURIComponent(account.room)}/messages/stream`;
      const abort = new AbortController();

      // Start SSE listener in background
      (async () => {
        while (!abort.signal.aborted) {
          try {
            const res = await fetch(sseUrl, {
              headers: { Accept: "text/event-stream" },
              signal: abort.signal,
            });
            if (!res.ok || !res.body) {
              log.warn(
                `[mycelium-channel] SSE connect failed (${res.status}) — retrying in 5s`
              );
              await new Promise((r) => setTimeout(r, 5000));
              continue;
            }

            log.info(`[mycelium-channel] SSE connected to ${account.room}`);
            const reader = (res.body as any).getReader();
            const decoder = new TextDecoder();
            let buffer = "";

            while (!abort.signal.aborted) {
              const { done, value } = await reader.read();
              if (done) break;

              buffer += decoder.decode(value, { stream: true });
              const blocks = buffer.split("\n\n");
              buffer = blocks.pop() ?? "";

              for (const block of blocks) {
                const dataLine = block
                  .split("\n")
                  .find((l: string) => l.startsWith("data: "));
                if (!dataLine) continue;
                const raw = dataLine.slice(6).trim();
                if (!raw || raw === "{}") continue;

                let msg: any;
                try {
                  msg = JSON.parse(raw);
                } catch {
                  continue;
                }

                // Skip our own messages
                if (msg.sender_handle === account.handle) continue;
                // Skip coordination messages (those go through the mycelium plugin, not channel)
                if (
                  msg.message_type === "coordination_tick" ||
                  msg.message_type === "coordination_consensus"
                )
                  continue;

                // Deliver inbound message to agent
                onInbound({
                  channel: "mycelium",
                  accountId: account.accountId,
                  peer: {
                    kind: "group",
                    id: account.room,
                    name: account.room,
                  },
                  sender: {
                    id: msg.sender_handle ?? "unknown",
                    name: msg.sender_handle ?? "unknown",
                  },
                  text: msg.content ?? "",
                  timestamp: msg.created_at ?? new Date().toISOString(),
                });
              }
            }
          } catch (err: any) {
            if (abort.signal.aborted) return;
            log.warn(
              `[mycelium-channel] SSE error: ${err?.message ?? err} — retrying in 5s`
            );
            await new Promise((r) => setTimeout(r, 5000));
          }
        }
      })();

      const state = createDefaultChannelRuntimeState();
      // Attach abort controller for cleanup
      (state as any)._abort = abort;
      return state;
    },

    stop: async ({ state }) => {
      (state as any)?._abort?.abort();
    },
  },
};
