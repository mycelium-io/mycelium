// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Environment + filesystem-backed config only. No HTTP (see http.ts).
 *
 * Responsibilities:
 *   - Load ~/.mycelium/config.json (or .toml fallback) for the backend URL and IDs
 *   - Resolve the agent handle from env or agentId
 *   - Read the per-turn memory injection file
 *   - Read the channels.mycelium-room config from openclaw.json
 */

import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

import { readMyceliumConfig } from "../read-mycelium-config.js";

export const MEMORY_FILE = join(
  homedir(),
  ".openclaw/workspace/memory/mycelium-context.md",
);

let apiUrl = (process.env.MYCELIUM_API_URL ?? "").replace(/\/$/, "");
let workspaceId = process.env.MYCELIUM_WORKSPACE_ID ?? "";
let masId = process.env.MYCELIUM_MAS_ID ?? "";

export function loadMyceliumConfig(): void {
  const cfg = readMyceliumConfig();
  const server = cfg.server ?? {};
  if (!process.env.MYCELIUM_API_URL && server.api_url) {
    apiUrl = server.api_url.replace(/\/$/, "");
  }
  if (!process.env.MYCELIUM_WORKSPACE_ID && server.workspace_id) {
    workspaceId = server.workspace_id;
  }
  if (!process.env.MYCELIUM_MAS_ID && server.mas_id) {
    masId = server.mas_id;
  }
}

export function getApiUrl(): string {
  return apiUrl;
}

export function getWorkspaceId(): string {
  return workspaceId;
}

export function getMasId(): string {
  return masId;
}

export function getAgentId(): string {
  return process.env.MYCELIUM_AGENT_ID ?? "";
}

export function resolveHandle(agentId?: string | null): string {
  if (process.env.MYCELIUM_AGENT_HANDLE) {
    return process.env.MYCELIUM_AGENT_HANDLE;
  }
  if (agentId?.trim()) {
    return agentId.trim();
  }
  const matrixId = process.env.MATRIX_USER_ID ?? "";
  if (matrixId.startsWith("@")) {
    return matrixId.slice(1).split(":")[0];
  }
  return matrixId || "unknown-agent";
}

/** Per-turn memory injection; fs only — no network in this module. */
export function readMemoryFileContent(): string | null {
  try {
    const memory = readFileSync(MEMORY_FILE, "utf-8").trim();
    return memory || null;
  } catch {
    return null;
  }
}

// ── Channel config (channels.mycelium-room in openclaw.json) ────────────────

export const CHANNEL_ID = "mycelium-room";

export type ChannelConfig = {
  backendUrl: string;
  room: string;
  agents: string[];
  requireMention: boolean;
};

type RawChannelEntry = {
  backendUrl?: string;
  room?: string;
  agents?: unknown[];
  handle?: string;
  requireMention?: boolean;
  enabled?: boolean;
  // Multi-room fan-out. When present, each entry becomes its own
  // ChannelConfig sharing this block's backendUrl + requireMention.
  // OpenClaw still only ever sees a single channel id (mycelium-room);
  // the N-room multiplexing is entirely internal to this plugin, which
  // avoids regenerating the plugin manifest / reinstalling on every room.
  rooms?: Array<{ room?: string; agents?: unknown[] }>;
};

function _agentsOf(
  entry: { agents?: unknown[]; handle?: string },
  fallback: string[] = ["main"],
): string[] {
  if (Array.isArray(entry.agents) && entry.agents.length > 0) {
    return entry.agents.map(String);
  }
  if (entry.handle) return [String(entry.handle)];
  return fallback;
}

/**
 * Read channels.mycelium-room from the OpenClaw config and expand it into one
 * ChannelConfig per room.
 *
 * Three shapes, all supported:
 *   1. Legacy single-room: { backendUrl, room, agents }            → [1 cfg]
 *   2. Multi-room fan-out:  { backendUrl, rooms: [{room,agents}] }  → [N cfg]
 *   3. Mixed: a top-level `room` PLUS `rooms[]`                     → all of them
 *
 * Returns [] when the channel is absent, disabled, or has no usable room —
 * in that case the plugin still installs session lifecycle handlers but
 * subscribes to no room SSE.
 */
export function readChannelConfigs(openclawConfig: unknown): ChannelConfig[] {
  const cfg = openclawConfig as { channels?: Record<string, unknown> } | null;
  const entry = cfg?.channels?.[CHANNEL_ID] as RawChannelEntry | undefined;

  if (!entry?.backendUrl) return [];
  if (entry.enabled === false) return [];

  const backendUrl = String(entry.backendUrl).replace(/\/$/, "");
  const requireMention = entry.requireMention !== false; // default true
  const out: ChannelConfig[] = [];
  const seen = new Set<string>();

  // Top-level single room (legacy + mixed).
  if (entry.room) {
    const room = String(entry.room);
    seen.add(room);
    out.push({ backendUrl, room, agents: _agentsOf(entry), requireMention });
  }

  // rooms[] fan-out.
  if (Array.isArray(entry.rooms)) {
    for (const r of entry.rooms) {
      if (!r?.room) continue;
      const room = String(r.room);
      if (seen.has(room)) continue; // de-dupe against the top-level room
      seen.add(room);
      out.push({
        backendUrl,
        room,
        agents: _agentsOf(r, []),
        requireMention,
      });
    }
  }

  return out;
}

/**
 * Back-compat shim for callers that only want the first/legacy single config
 * (e.g. session lifecycle, which is room-agnostic and only needs backendUrl).
 * Returns null when nothing is configured.
 */
export function readChannelConfig(openclawConfig: unknown): ChannelConfig | null {
  return readChannelConfigs(openclawConfig)[0] ?? null;
}
