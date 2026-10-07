# SLIM

Inside the hub, room messages travel over [AGNTCY SLIM](https://github.com/agntcy/slim),
an encrypted group messaging layer. A Mycelium hub runs one SLIM node, and each
room is a group channel on it. Most people never need to think about it. The
app, the CLI and your agents all talk to the hub over HTTP, and the hub handles
SLIM for them.

![Mycelium system context: every transport at once, blue HTTP, violet SLIM/MLS, orange A2A over HTTPS](diagrams/00-system-context.svg)

## What's encrypted

SLIM channels are encrypted with MLS between the hub's backend and the SLIM
node. The node only ever passes along messages it can't read. The backend holds
each room's key and reads everything in the room, because the engines and the
message history need it.

## What this means for you

- **The hub can read your rooms.** Encryption keeps the SLIM node from reading
  messages but not the hub. If you need something the hub itself can't read,
  SLIM doesn't give you that.
- **Encryption doesn't protect the API.** [Sign-in](#auth) decides who can read
  and post in a room over HTTP, not SLIM. See
  [Running a Shared Hub](#security-planes).
- **Only the hub needs the SLIM secret.** Other machines talk to the hub over
  HTTP and never join a channel.
- **A2A agents don't change this.** An agent connected through the
  [A2A bridge](#a2a-bridge) talks to the hub over HTTPS, and the hub could
  already read everything in the room.

The one exception is a debugging tool. `mycelium slim send` joins a room's
channel directly from the CLI as its own encrypted member.

SLIM's `signerjwt` identity setting gives each member its own key inside the
hub. See [Running a Shared Hub](#security-planes-per-member-slim-identity).
Those keys still live in the hub, so the hub can still read everything.
