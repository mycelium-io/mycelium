/**
 * Ingest target + control resolution.
 *
 * Reads ~/.mycelium/config.json (the snapshot the Python CLI writes on every
 * save) and layers environment variables on top. No network calls.
 */

import { readMyceliumConfig } from "../../extensions/mycelium/read-mycelium-config.js";

export function getIngestTarget() {
  const cfg = readMyceliumConfig();
  const server = cfg.server ?? {};
  return {
    apiUrl: process.env.MYCELIUM_API_URL || server.api_url || null,
    workspaceId: process.env.MYCELIUM_WORKSPACE_ID || server.workspace_id || null,
    masId: process.env.MYCELIUM_MAS_ID || server.mas_id || null,
    agentId:
      process.env.MYCELIUM_AGENT_ID || process.env.MYCELIUM_AGENT_HANDLE || null,
  };
}

const DEFAULT_CONFIG = {
  enabled: true,
  events: ["command:new", "agent:bootstrap"],
  maxToolContentBytes: 4096,
  skipInProgressTurn: true,
};

function envBool(name, fallback) {
  const raw = process.env[name];
  if (raw == null) return fallback;
  return !["0", "false", "no", "off", ""].includes(raw.toLowerCase());
}

function envInt(name, fallback) {
  const raw = process.env[name];
  if (raw == null) return fallback;
  const n = parseInt(raw, 10);
  return Number.isFinite(n) ? n : fallback;
}

function envList(name, fallback) {
  const raw = process.env[name];
  if (raw == null) return fallback;
  return raw
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

/**
 * Hook-side control surface. Returns the effective values after layering
 * MYCELIUM_INGEST_* env vars over the config.json snapshot, falling back to
 * DEFAULT_CONFIG. Backend-only knobs (max_input_tokens, dedupe_ttl_seconds)
 * are read by the backend via pydantic-settings and aren't surfaced here.
 */
export function getIngestConfig() {
  const cfg = readMyceliumConfig();
  const section = cfg.knowledge_ingest ?? {};

  return {
    enabled: envBool(
      "MYCELIUM_INGEST_ENABLED",
      section.enabled ?? DEFAULT_CONFIG.enabled,
    ),
    events: envList(
      "MYCELIUM_INGEST_EVENTS",
      section.events ?? DEFAULT_CONFIG.events,
    ),
    maxToolContentBytes: envInt(
      "MYCELIUM_INGEST_MAX_TOOL_CONTENT_BYTES",
      section.max_tool_content_bytes ?? DEFAULT_CONFIG.maxToolContentBytes,
    ),
    skipInProgressTurn: envBool(
      "MYCELIUM_INGEST_SKIP_IN_PROGRESS_TURN",
      section.skip_in_progress_turn ?? DEFAULT_CONFIG.skipInProgressTurn,
    ),
  };
}
