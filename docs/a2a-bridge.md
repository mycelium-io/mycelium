# The A2A bridge

Mycelium speaks [Agent2Agent (A2A)](https://github.com/a2aproject/A2A), the open
agent-interop protocol, in both directions. You can pull any A2A agent into a
room and talk to it like a teammate, and you can hand any room to an outside A2A
client as if the room itself were an agent.

## Bring an A2A agent into a room

Register a remote A2A endpoint as a room member. Mycelium resolves its Agent
Card at registration, so a bad URL fails right away instead of at first use.

```bash
mycelium agent create researcher --adapter a2a \
  --card https://research.example.com \
  --room my-room
```

Now `@researcher` is a member. Mention it in normal chat and it answers:

```
@researcher what did last quarter's numbers say about churn?
```

Under the hood the backend calls the remote agent over A2A with your message and
posts its reply back into the room as `@researcher`. Each mention continues the
same remote conversation (the thread's `contextId` is carried across turns), so
it remembers what you were talking about. This is plain chat, not a special
negotiation mode. When the aligner runs a negotiation and addresses `@researcher`,
that is just one more caller mentioning it.

If the remote agent needs a credential, name a backend env var that holds the
bearer token. The secret stays in the hub's environment; only the var name is
stored in the room.

```bash
mycelium agent create researcher --adapter a2a \
  --card https://research.example.com \
  --card-auth-env RESEARCHER_TOKEN
```

## Expose a room as an A2A agent

Every room is discoverable and callable as an A2A agent. Its Agent Card is served
at:

```
GET /api/rooms/{room}/.well-known/agent-card.json
```

The card advertises the room's name and its skills (drawn from the room's
`skills/` namespace). An external A2A client sends the room a message at
`POST /api/rooms/{room}/a2a`; the message lands in the room like any other post.
If it mentions a room agent, normal room dynamics take over, including the
inbound-to-outbound path where an incoming A2A message drives an A2A agent that
lives in the room.

The card endpoint is public (discovery is unauthenticated by the A2A spec, like
`/.well-known/openid-configuration`). The room's message endpoint is gated by the
hub's auth when auth is enabled.

## What the bridge is, and what it is not

A bridged A2A agent is a member of the room in the coordination sense: it is on
the roster, it answers when mentioned, its replies are attributed to its handle.

It is **not** a member of the room's end-to-end-encrypted MLS group. It never
holds a group key. The backend is a translation boundary: it reads the room's
plaintext and calls the remote agent out-of-band. Today that call is plain
HTTPS. It can be moved onto SLIM (SLIM identity, encrypted transport) via
`agntcy/slim-a2a-python`, but even then it is point-to-point RPC to a separate
SLIM identity, not membership in the room's group channel.

Practically: adding an A2A agent means the room's content is shared with that
external service over the network. The room's end-to-end encryption protects the
members of the group; it does not follow a message out to a bridged agent. Add
one the way you would grant any third party access to a conversation.
