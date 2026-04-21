# Reset Matrix, OpenClaw, and Mycelium (start over locally)

Use this when you want a **clean slate** on a dev machine. **Order:** stop services → remove Docker state → remove config directories.

**Warning:** This **deletes** homeserver data, chat history, OpenClaw agents/workspaces, Mycelium DB volumes, and CLI config. Copy anything you need before proceeding.

---

## 1. Stop running services

```bash
# OpenClaw gateway (user systemd — adjust if you use system-wide)
systemctl --user stop openclaw-gateway
systemctl --user disable openclaw-gateway   # optional

# Mycelium metrics collector (if running)
mycelium metrics stop 2>/dev/null || true
```

---

## 2. Matrix (Synapse in Docker)

From the directory that contains your **`docker-compose.yml`** for Synapse:

```bash
docker compose down -v
```

`-v` removes **named volumes** (e.g. Synapse DB / media). If Synapse data lives in a **bind-mounted** folder (e.g. `./data`), remove it explicitly:

```bash
sudo rm -rf ./data
# or wherever your compose file mounts Synapse /data
```

Remove any **generated** `homeserver.yaml` if you plan to run `generate` again.

---

## 3. Mycelium (Docker stack + CLI config)

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

## 4. OpenClaw

**All local OpenClaw state** for the Unix user:

```bash
rm -rf ~/.openclaw
```

This includes **`openclaw.json`**, workspaces, per-agent dirs, **`hooks/`**, **`extensions/`**, **`credentials/`** (including Matrix token cache), logs under **`/tmp/openclaw/`** if you want a clean log dir:

```bash
rm -rf /tmp/openclaw
```

If OpenClaw was installed as a **global npm/pnpm** tool, the CLI binary remains; only **data** is removed. To remove the tool itself, use your package manager (e.g. `npm uninstall -g openclaw` / `pnpm` / `uv tool uninstall mycelium-cli` as applicable).

---

## 5. Element (browser / desktop)

Sessions are **per client**. For a full UX reset, sign out of your homeserver in **Element** (or clear site data for your Element Web origin). This does **not** delete server-side accounts—that is separate (Synapse admin / deactivate users).

---

## 6. Mycelium adapter pieces (already covered by §4)

`mycelium adapter add openclaw` only writes under **`~/.openclaw/`** and **`~/.mycelium/config.toml`** (adapter registration). Removing **`~/.openclaw`** and **`~/.mycelium`** clears those.

---

## 7. Start again (short checklist)

1. Bring up **Synapse** (`generate` + `homeserver.yaml` + `up -d`).
2. Register Matrix users.
3. Install **OpenClaw**, recreate **`~/.openclaw`** via gateway / wizard.
4. Run **`mycelium install`** (if you use the backend) and **`mycelium adapter add openclaw`** / **`--step=otel`** as needed.
5. Follow **[openclaw-matrix-setup.md](openclaw-matrix-setup.md)** for Matrix + multi-agent wiring.

---

## Optional: selective cleanup

| Goal | Action |
|------|--------|
| Only Matrix | §2 only (+ Element sign-out if needed) |
| Only OpenClaw | §4 only |
| Only Mycelium backend | `docker compose … down -v` for mycelium + `rm -rf ~/.mycelium` |
| Keep Synapse, reset OpenClaw crypto | Stop gateway, remove only **`~/.openclaw/credentials/`** (and any matrix crypto subdirs under `~/.openclaw` if present), fix tokens in `openclaw.json`, restart |

---

*Paths assume a single Linux user; adjust for macOS (`$HOME` is the same idea).*
