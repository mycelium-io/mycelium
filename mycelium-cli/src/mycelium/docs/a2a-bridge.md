# A2A Bridge

Mycelium supports [Agent2Agent (A2A)](https://github.com/a2aproject/A2A), an
open protocol for agents to talk to each other. It works both ways. You can
add any A2A agent to a room and talk to it like a teammate, and outside A2A
clients can talk to a room as if the room were an agent.

You don't need to install anything on your machine for this. A bridged agent
is a remote HTTP endpoint, and the hub makes the calls to it.

## Adding an A2A agent to a room

Register the agent's URL as a room member. The hub reads its Agent Card when
you register it, so a wrong or unreachable URL fails straight away.

```bash
mycelium agent create researcher --adapter a2a \
    --card https://research.example.com \
    --room my-room
```

Now you can mention it in the room like anyone else:

```
@researcher what did last quarter's numbers say about churn?
```

The hub sends your message to the agent and posts its answer in the room as
`@researcher`. It keeps the same conversation going across mentions, so the
agent remembers what you were talking about. The aligner can address it in a
negotiation the same way.

If the agent needs a token, put the token in an environment variable on the
backend and give the variable's name. Only the name is saved in the room; the
token stays in the hub's environment.

```bash
mycelium agent create researcher --adapter a2a \
    --card https://research.example.com \
    --card-auth-env RESEARCHER_TOKEN
```

Some safeguards:

- **Only public addresses.** The hub won't register a card URL that points to
  a private or local network address, so a registration can't be used to make
  the backend call into its own network. If your A2A agents are on an internal
  network you trust, turn this off:

  ```
  mycelium config set a2a.allow_private_hosts true
  mycelium config apply
  ```

  This sets `A2A_ALLOW_PRIVATE_HOSTS=1` on the backend. Don't do this on a
  hub that's open to the internet.
- **Bridged agents don't set each other off.** A reply from one A2A agent never
  triggers another, so two of them can't get stuck mentioning each other.
  People, the aligner and your own agents still get replies.
- **No made-up replies.** If the remote agent is down or sends something
  unreadable, nothing is posted.

![A remote A2A agent joins the room as a member: the hub calls it over HTTPS and posts its reply in the room](diagrams/02-a2a-outbound.svg)

## Talking to a room over A2A

Every room can be found and called as an A2A agent, with no setup. Its Agent
Card is at:

```
GET /api/rooms/{room}/.well-known/agent-card.json
```

The card lists the room's name and its skills, taken from the room's
`skills/` memories. An A2A client sends the room a message with A2A JSON-RPC
(`message/send`) at:

```
POST /api/rooms/{room}/a2a
```

The message is posted in the room like any other, and the call returns an
acknowledgement. If it mentions an agent in the room, that agent answers as
usual, including an A2A agent bridged into the room.

Anyone can read the card, as the A2A spec expects. Sending messages requires
a login when [authentication](reference.html#auth) is on. With authentication
on, the message is posted under the caller's name: a call made as
`claude-web` shows up as `@claude-web`. Without authentication there's no way
to know who called, so messages are posted as `@a2a-guest`.

The card contains the room's full URL, built from the scheme the hub sees.
Behind a proxy that handles TLS, the hub sees plain `http`, so you need to tell
it which proxy to trust or the card will point clients at `http://`. See
[Behind a TLS-terminating proxy](reference.html#hub-and-spoke).

![The room as an A2A agent: clients read its card and send messages that are posted in the room](diagrams/03-a2a-inbound.svg)

## Seeing what the bridge is doing

`mycelium network [room]` shows the bridge for each room below the network
table: the bridged agents with their URLs and skills, the room's own card and
how often it's been read, and the most recent calls in each direction, with
what came back or why it failed.

```bash
mycelium network my-room
```

In the app, the **Network** pane shows the same thing in a strip under the
SLIM view. Rooms without a bridge don't show it.

To get the raw data:

```
GET /api/rooms/{room}/a2a/state
```

These counts are kept in memory and reset when the hub restarts. The room's
messages, including replies from bridged agents, are saved as usual.

## Privacy

A bridged A2A agent can be mentioned and answers under its own name, but it
isn't part of the room's encrypted group and never has the room's key. The hub
reads the room's messages and sends them to the remote agent over HTTPS.

The hub can already read everything in the room. It needs to, for engines to
work (see [SLIM](index.html#slim)). Adding an A2A agent means sending some of
the room's content to another service as well, so add one the way you'd give
any outside party access to a conversation.
