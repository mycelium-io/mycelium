/**
 * Ingest target resolution — env + ~/.mycelium/config.toml only (no network calls).
 */

import { readMyceliumServerFromToml } from "../../extensions/mycelium/read-mycelium-config.js";

export function getIngestTarget() {
  const cfg = readMyceliumServerFromToml();
  return {
    apiUrl: process.env.MYCELIUM_API_URL || cfg.api_url || null,
    workspaceId: process.env.MYCELIUM_WORKSPACE_ID || cfg.workspace_id || null,
    masId: process.env.MYCELIUM_MAS_ID || cfg.mas_id || null,
    agentId:
      process.env.MYCELIUM_AGENT_ID || process.env.MYCELIUM_AGENT_HANDLE || null,
  };
}
