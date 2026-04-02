// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

// ── Environment-sourced config ────────────────────────────────────────────────
// All process.env access is isolated here, away from any network calls.
// index.ts imports these values — no process.env reads there.

export const AGENT_ID = process.env.MYCELIUM_AGENT_ID ?? "";
export const AGENT_HANDLE = process.env.MYCELIUM_AGENT_HANDLE ?? "";
export const MATRIX_USER_ID = process.env.MATRIX_USER_ID ?? "";

// Initial values from env vars — may be overridden by loadMyceliumConfig()
const ENV_API_URL = (process.env.MYCELIUM_API_URL ?? "").replace(/\/$/, "");
const ENV_WORKSPACE_ID = process.env.MYCELIUM_WORKSPACE_ID ?? "";
const ENV_MAS_ID = process.env.MYCELIUM_MAS_ID ?? "";

// ── Config file loading ───────────────────────────────────────────────────────

const CONFIG_PATH = join(homedir(), ".mycelium", "config.toml");

/** Extract a single key from a named TOML section. Handles quoted and bare values. */
function parseTomlField(toml: string, section: string, key: string): string | undefined {
  const sectionMatch = toml.match(new RegExp(`\\[${section}\\]([^\\[]*)`, "s"));
  if (!sectionMatch) return undefined;
  const kvMatch = sectionMatch[1].match(
    new RegExp(`^\\s*${key}\\s*=\\s*["']?([^"'\\n\\r]+?)["']?\\s*$`, "m")
  );
  return kvMatch?.[1]?.trim();
}

export type MyceliumConfig = {
  apiUrl: string;
  workspaceId: string;
  masId: string;
};

/**
 * Load config from ~/.mycelium/config.toml. Env vars take precedence.
 * Returns resolved values — no execSync, no network.
 */
export function loadMyceliumConfig(): MyceliumConfig {
  let apiUrl = ENV_API_URL;
  let workspaceId = ENV_WORKSPACE_ID;
  let masId = ENV_MAS_ID;

  try {
    const toml = readFileSync(CONFIG_PATH, "utf-8");
    if (!ENV_API_URL) {
      const val = parseTomlField(toml, "server", "api_url");
      if (val) apiUrl = val.replace(/\/$/, "");
    }
    if (!ENV_WORKSPACE_ID) {
      const val = parseTomlField(toml, "server", "workspace_id");
      if (val) workspaceId = val;
    }
    if (!ENV_MAS_ID) {
      const val = parseTomlField(toml, "server", "mas_id");
      if (val) masId = val;
    }
  } catch {
    // Config file missing or unreadable — rely on env vars alone
  }

  return { apiUrl, workspaceId, masId };
}
