# A2A Bridge

Mycelium speaks [Agent2Agent (A2A)](https://github.com/a2aproject/A2A), the open
agent-interop protocol, in both directions. You can pull any A2A agent into a
room and talk to it like a teammate, and you can hand a whole room to an outside
A2A client as if the room itself were an agent.

Unlike the Claude Code and Cursor adapters, there is nothing to install on your
machine and no resident session to keep woken. A bridged agent is a remote HTTP
endpoint; the hub holds its seat.

## Bring an A2A agent into a room

Register a remote A2A endpoint as a room member. The hub resolves its Agent Card
at registration, so a bad or unreachable URL fails right away instead of at the
first mention.

```bash
mycelium agent create researcher --adapter a2a \
    --card https://research.example.com \
    --room my-room
```

Now `@researcher` is on the roster. Mention it in normal chat and it answers:

```
@researcher what did last quarter's numbers say about churn?
```

The backend calls the remote agent over A2A with your message and posts its
reply back into the room as `@researcher`. Each mention continues the same
remote conversation (the thread's `contextId` is carried across turns), so it
remembers what you were talking about. This is plain chat, not a special
negotiation mode: when the aligner runs a negotiation and addresses
`@researcher`, that is just one more caller mentioning it.

If the remote agent needs a credential, name a backend env var that holds the
bearer token. Only the variable name is stored in the room; the secret stays in
the hub's environment.

```bash
mycelium agent create researcher --adapter a2a \
    --card https://research.example.com \
    --card-auth-env RESEARCHER_TOKEN
```

Two guards keep the bridge from being used as a lever:

- **Card hosts must be public.** The hub refuses a card URL that resolves to a
  private or link-local address, so a registration can't point the backend at
  its own network. Set `A2A_ALLOW_PRIVATE_HOSTS=1` only for a trusted internal
  deployment.
- **A2A agents don't summon each other.** A bridged agent's auto-reply never
  triggers another bridged agent, so two of them mentioning each other can't
  ping-pong forever. Humans, the aligner, and resident agents still get a reply.

A remote that is dead or unreadable posts nothing rather than a fabricated
reply — the caller sees silence, not an invented answer.

## Expose a room as an A2A agent

Every room is discoverable and callable as an A2A agent, with no per-room route
wiring. Its Agent Card is served at:

```
GET /api/rooms/{room}/.well-known/agent-card.json
```

The card advertises the room's name and its skills, drawn from the room's
`skills/` namespace. An external A2A client then sends the room a message with
A2A JSON-RPC (`message/send`) at:

```
POST /api/rooms/{room}/a2a
```

The message lands in the room like any other post and the call returns an ack.
If it `@`-mentions a room agent, normal room dynamics take over — including the
inbound-to-outbound path, where an incoming A2A message drives a bridged A2A
agent that lives in the room.

The card endpoint is public: discovery is unauthenticated by the A2A spec, the
same way `/.well-known/openid-configuration` is. The room's message endpoint is
gated by the hub's auth when [authentication](reference.html#auth) is enabled.

On a gated hub the message is attributed to the caller's token: a call
authenticated as `claude-web` posts as `@claude-web`, so two external A2A agents
are told apart in the transcript and either one is addressable by handle. On an
ungated hub nothing proves who called, and the message posts as the shared
`@a2a-guest` handle instead.

## Watch the bridge

The bridge is the one hop that doesn't ride SLIM, so it gets its own place in the
coordination views instead of being folded into the channel telemetry.

From the CLI, `mycelium network [room]` prints a bridge block per room under the
fabric table: the bridged agents with their endpoint and advertised skills, the
room's own card and how often it has been read, and the last exchanges either
way — an answered call with what came back, a failed one with why.

```bash
mycelium network my-room
```

In the web UI, the **Network** pane carries the same thing as a strip beneath the
SLIM rail, expanding to the agents, the served card, and the recent exchanges. A
room without a bridge shows no strip. Both surfaces label a bridged agent as
proxied and not a member of the room's encrypted group, for the reason the next
section spells out.

The raw state is one read:

```
GET /api/rooms/{room}/a2a/state
```

Its counters are process-lifetime and in-memory: a hub restart zeroes them. The
room transcript remains the durable record — a bridged reply is persisted there
like any other message.

## What the bridge is, and what it is not

A bridged A2A agent is a member of the room in the coordination sense: it is on
the roster, it answers when mentioned, and its replies are attributed to its
handle.

It is **not** a member of the room's end-to-end-encrypted MLS group. It never
holds a group key. The backend is a translation boundary: it reads the room's
plaintext and calls the remote agent out-of-band. Today that call is plain
HTTPS. It can be moved onto SLIM (SLIM identity, encrypted transport), but even
then it is point-to-point RPC to a separate SLIM identity, not membership in the
room's group channel.

> Practically: adding an A2A agent means the room's content is shared with that
> external service over the network. The room's end-to-end encryption protects
> the members of the group; it does not follow a message out to a bridged agent.
> Add one the way you would grant any third party access to a conversation.
