/**
 * Ingest target resolution — env + ~/.mycelium/config.json only (no network calls).
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
