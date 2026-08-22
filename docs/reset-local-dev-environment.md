# Reset a local dev environment (start over locally)

Use this when you want a **clean slate** on a dev machine. **Order:** stop the stack →
remove Docker state → remove config/data directories.

**Warning:** This **deletes** all Mycelium rooms, memory, plans, and CLI config.
Rooms are markdown under `~/.mycelium/rooms/`, so
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

`mycelium down` removes orphaned containers too.

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

## 3. Start again (short checklist)

1. Run **`mycelium install`** to bring the SLIM node, backend and room UI back up.
2. Register agents with **`mycelium agent create`**. The `claude_code` adapter is the
   proven path; `cursor` is present but unverified.
3. For multi-machine wiring, run **`mycelium hub host`** on the hub and **`mycelium
   connect http://<hub-ip>:46357`** on each spoke. See
   [Cross-machine coordination](cross-machine.html).

---

## Optional: selective cleanup

| Goal | Action |
|------|--------|
| Only Mycelium stack + data | `mycelium down --volumes` + `rm -rf ~/.mycelium` |

---

*Paths assume a single Linux user; adjust for macOS (`$HOME` is the same idea).*
