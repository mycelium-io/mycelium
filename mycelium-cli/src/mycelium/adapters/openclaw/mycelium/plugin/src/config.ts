// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

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

/**
 * Read channels.mycelium-room from the OpenClaw config that was passed to the
 * plugin at register time. Returns null if the channel isn't configured —
 * in that case the plugin still installs session lifecycle handlers but
 * doesn't subscribe to any room SSE.
 */
export function readChannelConfig(openclawConfig: unknown): ChannelConfig | null {
  const cfg = openclawConfig as { channels?: Record<string, unknown> } | null;
  const entry = cfg?.channels?.[CHANNEL_ID] as
    | {
        backendUrl?: string;
        room?: string;
        agents?: unknown[];
        handle?: string;
        requireMention?: boolean;
        enabled?: boolean;
      }
    | undefined;

  if (!entry?.backendUrl || !entry?.room) return null;
  if (entry.enabled === false) return null;

  let agents: string[];
  if (Array.isArray(entry.agents) && entry.agents.length > 0) {
    agents = entry.agents.map(String);
  } else if (entry.handle) {
    agents = [String(entry.handle)];
  } else {
    agents = ["main"];
  }

  return {
    backendUrl: String(entry.backendUrl).replace(/\/$/, ""),
    room: String(entry.room),
    agents,
    requireMention: entry.requireMention !== false, // default true
  };
}
