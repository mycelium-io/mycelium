# Reset a local dev environment (start over locally)

Use this when you want a **clean slate** on a dev machine. **Order:** stop the stack →
remove Docker state → remove config/data directories.

**Warning:** This **deletes** all Mycelium rooms, memory, plans, and CLI config (and, if
you run it, OpenClaw agents/workspaces). Rooms are markdown under `~/.mycelium/rooms/`, so
copy anything you need before proceeding. There is no database; room and memory state
lives entirely in files.

---

## 1. Stop the stack

The current stack is the SLIM node (`mycelium-slim`) plus the backend
(`mycelium-backend`), with the frontend (`mycelium-frontend`) and OTLP collector
(`mycelium-collector`) as opt-in profiles. Tear it all down with the CLI: no `--profile
cfn`, no separate DB container:

```bash
mycelium down --volumes        # stop every service and drop volumes (destructive)
```

`mycelium down` removes orphaned containers too. If you never installed the stack, or you
run OpenClaw's gateway separately:

```bash
# OpenClaw gateway (user systemd; adjust if you use system-wide)
systemctl --user stop openclaw-gateway
systemctl --user disable openclaw-gateway   # optional
```

If `mycelium` isn't on PATH, drive compose directly from the compose project (files under
**`~/.mycelium/docker/`**):

```bash
docker compose -p mycelium -f "$HOME/.mycelium/docker/compose.yml" down -v --remove-orphans
```

---

## 2. Mycelium config and data

```bash
rm -rf ~/.mycelium
```

That removes **`rooms/`** (all room markdown, memory, and plans), **`config.toml`**,
**`docker/`** (compose copy), **`.env`**, and **metrics** (`metrics.json`,
`collector.pid`).

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

1. Run **`mycelium install`** to bring the SLIM node + backend back up, then
   **`mycelium up --ui`** if you want the room UI (the frontend is opt-in).
2. Register agents with **`mycelium agent create`**. The `claude_code` adapter is the
   proven path; `openclaw`/`hermes` are deprecated (they rode the removed SSE path).
3. For multi-machine wiring, run **`mycelium hub host`** on the hub and **`mycelium
   connect http://<hub-ip>:46357`** on each spoke. See
   [Cross-machine coordination](cross-machine.html).

---

## Optional: selective cleanup

| Goal | Action |
|------|--------|
| Only OpenClaw | §3 only |
| Only Mycelium stack + data | `mycelium down --volumes` + `rm -rf ~/.mycelium` |
| Reset OpenClaw crypto only | Stop gateway, remove only **`~/.openclaw/credentials/`**, fix tokens in `openclaw.json`, restart |

---

*Paths assume a single Linux user; adjust for macOS (`$HOME` is the same idea).*
