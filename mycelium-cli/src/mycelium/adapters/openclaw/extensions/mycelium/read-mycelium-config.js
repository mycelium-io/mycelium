/**
 * Read ~/.mycelium/config.toml [server] section without spawning the mycelium CLI.
 * Bundled with the OpenClaw plugin; hooks import via ../../extensions/mycelium/read-mycelium-config.js.
 */
import fs from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

/**
 * @returns {{ api_url?: string; workspace_id?: string; mas_id?: string }}
 */
export function readMyceliumServerFromToml() {
  const path = join(homedir(), ".mycelium", "config.toml");
  try {
    const text = fs.readFileSync(path, "utf-8");
    return parseServerSection(text);
  } catch {
    return {};
  }
}

/**
 * @param {string} text
 * @returns {{ api_url?: string; workspace_id?: string; mas_id?: string }}
 */
export function parseServerSection(text) {
  /** @type {Record<string, string>} */
  const keys = {};
  let inServer = false;
  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    if (/^\[server\]\s*$/i.test(trimmed)) {
      inServer = true;
      continue;
    }
    if (trimmed.startsWith("[") && trimmed.endsWith("]")) {
      inServer = false;
      continue;
    }
    if (!inServer) continue;
    const eq = trimmed.indexOf("=");
    if (eq <= 0) continue;
    const key = trimmed.slice(0, eq).trim();
    let val = trimmed.slice(eq + 1).trim();
    if (
      (val.startsWith('"') && val.endsWith('"')) ||
      (val.startsWith("'") && val.endsWith("'"))
    ) {
      val = val.slice(1, -1).replace(/\\"/g, '"');
    }
    keys[key] = val;
  }
  return {
    api_url: keys.api_url,
    workspace_id: keys.workspace_id,
    mas_id: keys.mas_id,
  };
}
