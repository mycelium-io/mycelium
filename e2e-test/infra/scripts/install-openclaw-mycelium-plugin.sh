#!/usr/bin/env bash
# Manually stage the bundled mycelium OpenClaw plugin into ~/.openclaw/extensions.
#
# ``openclaw plugins install`` rejects our committed dist/index.js on recent
# OpenClaw builds (directory boundary checks). The product CLI mirrors dist/
# after install, but the install step itself fails first. This infra script
# copies the wheel-shipped plugin + hooks directly and registers them in
# openclaw.json — no mycelium-cli changes required.

set -euo pipefail

CONFIG_DIR="${OPENCLAW_STATE_DIR:-${HOME}/.openclaw}"
CONFIG_PATH="${CONFIG_DIR}/openclaw.json"
PY="${MYCELIUM_PYTHON:-/usr/local/share/uv/tools/mycelium-cli/bin/python}"

if [ ! -x "$PY" ]; then
    echo "[install-openclaw-mycelium-plugin] mycelium python not found at ${PY}" >&2
    exit 1
fi

"$PY" - "$CONFIG_DIR" "$CONFIG_PATH" <<'PY'
import json
import shutil
import sys
from pathlib import Path

import mycelium

config_dir = Path(sys.argv[1])
config_path = Path(sys.argv[2])
assets = Path(mycelium.__file__).parent / "integrations/openclaw/assets/mycelium"
plugin_src = assets / "plugin"
hooks_src = assets / "hooks"

if not (plugin_src / "dist" / "index.js").exists():
    raise SystemExit(f"[install-openclaw-mycelium-plugin] missing dist in {plugin_src}")

ext_dir = config_dir / "extensions" / "mycelium"
if ext_dir.exists():
    shutil.rmtree(ext_dir)
shutil.copytree(
    plugin_src,
    ext_dir,
    ignore=shutil.ignore_patterns("node_modules", "test", "package-lock.json"),
)

for hook_name in hooks_src.iterdir() if hooks_src.exists() else []:
    if not hook_name.is_dir():
        continue
    dest = config_dir / "hooks" / hook_name.name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(hook_name, dest)

if config_path.exists():
    cfg = json.loads(config_path.read_text())
else:
    cfg = {}

plugins = cfg.setdefault("plugins", {})
allow = plugins.setdefault("allow", [])
for pid in ("litellm", "matrix", "mycelium"):
    if pid not in allow:
        allow.append(pid)

entries = plugins.setdefault("entries", {})
entries.setdefault("mycelium", {"enabled": True})
entries.setdefault("matrix", {"enabled": True})
entries.setdefault("litellm", {"enabled": True})

load = plugins.setdefault("load", {})
paths = load.setdefault("paths", [])
ext_str = str(ext_dir)
if ext_str not in paths:
    paths.append(ext_str)

config_dir.mkdir(parents=True, exist_ok=True)
config_path.write_text(json.dumps(cfg, indent=2) + "\n")
print(f"[install-openclaw-mycelium-plugin] staged plugin → {ext_dir}")
print(f"[install-openclaw-mycelium-plugin] updated {config_path}")
PY

/openclaw/restart-openclaw-gateway.sh 2>/dev/null || true
