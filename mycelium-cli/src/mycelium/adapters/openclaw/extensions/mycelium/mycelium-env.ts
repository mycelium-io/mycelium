// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

/**
 * Environment and filesystem-backed config only — no HTTP (see mycelium-http.ts).
 */

import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

import { readMyceliumConfig } from "./read-mycelium-config.js";

export const MEMORY_FILE = join(
  homedir(),
  ".openclaw/workspace/memory/mycelium-context.md"
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
