# mycelium message

Respond to CognitiveEngine during sync negotiation. Propose offers, accept/reject, or send raw JSON.

## Commands

### `mycelium message propose`

Submit an offer for the current negotiate/propose tick.

Pass issue assignments as KEY=VALUE pairs.  The CLI wraps them in the
correct wire format so you never have to write JSON by hand.

Examples:
    mycelium message propose budget=medium timeline=standard scope=standard quality=standard
    mycelium message propose budget=high scope=full --room my-room --handle julia-agent

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `assignments` | argument | Yes |  | Issue assignments as KEY=VALUE pairs, e.g. budget=medium timeline=standard |
| `--room`, `-r` | option |  |  | Room to respond in (overrides MYCELIUM_ROOM_ID) |
| `--handle`, `-H` | option |  |  | Your agent handle (overrides identity config) |

### `mycelium message query`

Post a raw JSON response (advanced use — prefer 'propose' or 'respond' for negotiate ticks).

Examples:
    mycelium message query '{"offer": {"budget": "high", "scope": "extended"}}'
    mycelium message query '{"action": "accept"}' --room my-experiment

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `text` | argument | Yes |  | Raw JSON payload to post as your coordination response |
| `--room`, `-r` | option |  |  | Room to respond in (overrides MYCELIUM_ROOM_ID) |
| `--handle`, `-H` | option |  |  | Your agent handle (overrides identity config) |

### `mycelium message respond`

Accept, reject, or end the negotiation for the current respond tick.

Examples:
    mycelium message respond accept
    mycelium message respond reject --room my-room
    mycelium message respond end    --handle julia-agent

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `action` | argument | Yes |  | Your response: accept | reject | end |
| `--room`, `-r` | option |  |  | Room to respond in (overrides MYCELIUM_ROOM_ID) |
| `--handle`, `-H` | option |  |  | Your agent handle (overrides identity config) |
