# Reset OpenClaw and Mycelium (start over locally)

Use this when you want a **clean slate** on a dev machine. **Order:** stop services → remove Docker state → remove config directories.

**Warning:** This **deletes** OpenClaw agents/workspaces, Mycelium DB volumes, and CLI config. Copy anything you need before proceeding.

---

## 1. Stop running services

```bash
# OpenClaw gateway (user systemd — adjust if you use system-wide)
systemctl --user stop openclaw-gateway
systemctl --user disable openclaw-gateway   # optional

# Mycelium metrics collector (Docker — if running)
docker stop mycelium-collector 2>/dev/null && docker rm mycelium-collector 2>/dev/null || true
```

---

## 2. Mycelium (Docker stack + CLI config)

If you installed the full stack with **`mycelium install`**, from the compose project (often files under **`~/.mycelium/docker/`**):

```bash
docker compose -p mycelium -f "$HOME/.mycelium/docker/compose.yml" down -v
```

Or use the same **`-p`** / **`-f`** / **`--env-file`** you use for `mycelium install`. `-v` drops DB volumes (e.g. `mycelium-db-data`).

**CLI and extracted files:**

```bash
rm -rf ~/.mycelium
```

That removes **`config.toml`**, **`docker/`** (compose + initdb copy), **`.env`**, **metrics** (`metrics.json`, `collector.pid`), etc.

---

## 3. OpenClaw

**All local OpenClaw state** for the Unix user:

```bash
rm -rf ~/.openclaw
```

This includes **`openclaw.json`**, workspaces, per-agent dirs, **`hooks/`**, **`extensions/`**, **`credentials/`** (including any channel token cache), logs under **`/tmp/openclaw/`** if you want a clean log dir:

```bash
rm -rf /tmp/openclaw
```

If OpenClaw was installed as a **global npm/pnpm** tool, the CLI binary remains; only **data** is removed. To remove the tool itself, use your package manager (e.g. `npm uninstall -g openclaw` / `pnpm` / `uv tool uninstall mycelium-cli` as applicable).

---

## 4. Mycelium adapter pieces (already covered by §3)

`mycelium adapter add openclaw` only writes under **`~/.openclaw/`** and **`~/.mycelium/config.toml`** (adapter registration). Removing **`~/.openclaw`** and **`~/.mycelium`** clears those.

---

## 5. Start again (short checklist)

1. Install **OpenClaw**, recreate **`~/.openclaw`** via gateway / wizard.
2. Run **`mycelium install`** (if you use the backend) and **`mycelium adapter add openclaw`** / **`--step=otel`** as needed.
3. Add agents with **`mycelium agent add`** — this auto-wires the OpenClaw `mycelium-room` channel (the Mycelium room UI). For multi-machine / multi-agent wiring, follow the **[Hub & Spoke Setup](../mycelium-cli/src/mycelium/docs/guides/hub-and-spoke.md)** guide.

---

## Optional: selective cleanup

| Goal | Action |
|------|--------|
| Only OpenClaw | §3 only |
| Only Mycelium backend | `docker compose … down -v` for mycelium + `rm -rf ~/.mycelium` |
| Reset OpenClaw crypto only | Stop gateway, remove only **`~/.openclaw/credentials/`**, fix tokens in `openclaw.json`, restart |

---

*Paths assume a single Linux user; adjust for macOS (`$HOME` is the same idea).*
