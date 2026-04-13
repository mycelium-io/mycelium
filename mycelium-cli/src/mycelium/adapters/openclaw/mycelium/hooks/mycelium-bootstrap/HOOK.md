---
name: mycelium-bootstrap
description: Sets MYCELIUM_ROOM_ID and MYCELIUM_API_URL env vars on agent bootstrap, derived from the channel/conversation context.
metadata:
  openclaw:
    emoji: "🐝"
    events:
      - agent:bootstrap
---

Sets `MYCELIUM_ROOM_ID` from the channel/conversation context (Matrix room, Slack channel, etc.) and forwards `MYCELIUM_API_URL` from gateway env into the agent session. Coordination instructions are injected by the mycelium plugin (`index.ts`) via `prependSystemContext`.
