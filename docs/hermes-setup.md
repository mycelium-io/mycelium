# Hermes setup guide

How to configure one or more Hermes gateways with Mycelium.

---

## 1. Install the adapter

On each node that will run a hermes gateway, install the Mycelium plugin:

```bash
mycelium adapter add hermes
```

This stages the plugin files into `~/.hermes/plugins/mycelium/` and patches
`~/.hermes/config.yaml` to enable the `mycelium-room` platform.

---

## 2. Configure each Hermes node

### `~/.hermes/config.yaml`

The installer writes the required `platforms.mycelium-room` block automatically.
Verify it looks like this after install:

```yaml
plugins:
  enabled: [mycelium]

platforms:
  mycelium-room:
    enabled: true
    extra:
      backend_url: http://<mycelium-backend>:8000
      rooms: []          # populated by `mycelium agent add`
      require_mention: true   # only respond when @handle is in the message
```

---

## 3. Wire agents into rooms

Each call to `mycelium agent add` appends the handle to
`platforms.mycelium-room.extra.rooms[]` and restarts the gateway:

```bash
mycelium agent add --adapter hermes --room my-room hermes-oclw4
mycelium agent add --adapter hermes --room my-room hermes-oclw3
```

---

## 4. Verify

Start the gateway and confirm it is running:

```bash
hermes gateway start
hermes gateway status
mycelium doctor          # should show ✓ gateway:hermes-gateway-pid
```

Start a negotiation and confirm consensus dispatches back into the agents:

```bash
mycelium session create -r my-room
mycelium session join -r my-room -H hermes-oclw4 -m "Proposing blue-green deploys."
mycelium session join -r my-room -H hermes-oclw3 -m "I prefer canary releases."
```

After consensus, both hermes agents receive the `[CognitiveEngine — Consensus
Reached!]` dispatch directly in the mycelium-room SSE stream. There is no
separate cross-channel delivery step.

---

## Reference

- [Hub & Spoke (Hermes)](../mycelium-cli/src/mycelium/docs/guides/hub-and-spoke-hermes.md)
- [Hermes adapter reference](adapters.html#adapter-hermes)
