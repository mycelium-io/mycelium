#!/usr/bin/env bash
# Copy the bundled mycelium OpenClaw skill into every configured agent workspace.
#
# Mycelium's adapter install drops the skill under the default workspace only.
# Hub/spoke entrypoints create per-agent workspaces (workspace-<id>) *after*
# adapter install, and E2E provisioning may add agents later via
# ``mycelium agent add``. This script mirrors the product-side
# ``_install_openclaw_skill`` behaviour without requiring mycelium-cli changes.
#
# Usage:
#   install-openclaw-skills.sh              # all agents in openclaw.json
#   install-openclaw-skills.sh agent-alpha  # one agent by id

set -euo pipefail

CONFIG_DIR="${OPENCLAW_STATE_DIR:-${HOME}/.openclaw}"
CONFIG_PATH="${CONFIG_DIR}/openclaw.json"
SKILL_NAME=mycelium

find_skill_source() {
    local candidate
    for candidate in \
        "${CONFIG_DIR}/extensions/mycelium/skills/${SKILL_NAME}" \
        "${CONFIG_DIR}/workspace/skills/${SKILL_NAME}"; do
        if [ -f "${candidate}/SKILL.md" ]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

main() {
    local skill_src
    if ! skill_src="$(find_skill_source)"; then
        echo "[install-openclaw-skills] no ${SKILL_NAME} skill under ${CONFIG_DIR} — skipping" >&2
        return 0
    fi

    if [ ! -f "$CONFIG_PATH" ]; then
        echo "[install-openclaw-skills] no ${CONFIG_PATH} — skipping" >&2
        return 0
    fi

    local only_agent="${1:-}"
    node - "$CONFIG_PATH" "$CONFIG_DIR" "$skill_src" "$only_agent" <<'NODE'
const fs = require('fs');
const path = require('path');

const [configPath, configDir, skillSrc, onlyAgent] = process.argv.slice(2);
const cfg = JSON.parse(fs.readFileSync(configPath, 'utf8'));
const defaultWorkspace = (
  cfg.agents?.defaults?.workspace || path.join(configDir, 'workspace')
).replace(/^~/, process.env.HOME || '');

const workspaces = new Set();
for (const entry of cfg.agents?.list || []) {
  if (!entry || typeof entry !== 'object') continue;
  const id = String(entry.id || '').trim();
  if (!id) continue;
  if (onlyAgent && id !== onlyAgent) continue;
  const explicit = String(entry.workspace || '').trim();
  if (explicit) {
    workspaces.add(explicit.replace(/^~/, process.env.HOME || ''));
  } else if (id === 'main') {
    workspaces.add(defaultWorkspace);
  } else {
    workspaces.add(path.join(configDir, `workspace-${id}`));
    workspaces.add(path.join(configDir, 'workspaces', id));
  }
}
workspaces.add(defaultWorkspace);

for (const workspace of workspaces) {
  const dest = path.join(workspace, 'skills', 'mycelium');
  fs.mkdirSync(dest, { recursive: true });
  for (const name of fs.readdirSync(skillSrc)) {
    fs.copyFileSync(path.join(skillSrc, name), path.join(dest, name));
  }
  console.log(`[install-openclaw-skills] → ${dest}`);

  const agentsMd = path.join(workspace, 'AGENTS.md');
  const mandate = [
    '# Mycelium coordination (E2E)',
    '',
    'When you receive a `[CognitiveEngine — Round` message, you **must** run the',
    '`mycelium negotiate ...` shell command it specifies. Prose-only accept/reject',
    'replies do **not** register with CognitiveEngine.',
    '',
  ].join('\n');
  fs.writeFileSync(agentsMd, mandate);
  console.log(`[install-openclaw-skills] → ${agentsMd}`);
}
NODE
}

main "$@"
