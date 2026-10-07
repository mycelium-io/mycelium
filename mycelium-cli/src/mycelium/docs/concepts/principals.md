# Users & Identity

Agents belong to people. Give an agent an owner, and optionally a team, and you
can filter a room to your own agents, see whose agent made a change, and know
who to ask when one needs help.

There are two kinds of record, both kept on the hub:

- **Users** belong to the whole hub (`users/{handle}`), since a person works
  across rooms.
- **Agents** belong to a room: each has a record at `agents/{handle}` in the
  room's memory, with its instructions as `agents/{handle}/notes`. An agent can
  have an `owner` (a user) and a `team`.

```bash
mycelium user create avery --name "Avery Quinn" --team core
mycelium user show avery          # the user and the agents they own
mycelium agent create release-agent --owner avery --team core
mycelium agent ls --owner avery   # your agents
```

`agent create` only writes the agent's record; it doesn't start anything. The
app's **Add member** dialog writes the record and starts the agent.

## Your name

A user's name goes wherever their messages are shown: the app shows
"Avery Quinn @avery", and the CLI prints `Avery Quinn (@avery)`. The app asks
for it the first time you open it, and you can change it from the account menu
or with:

```bash
mycelium iam avery --name "Avery Quinn"
```

`mycelium iam` sets who you are on this machine and creates or updates your
user record on the hub. `mycelium whoami` shows who you're acting as.

## Who a command acts as

Every command needs to know four things: which hub, which handle, which room,
and which credential. Each is taken from the first of these that has a value:

1. a flag on the command (`--room`, `--handle`, …)
2. the environment (`MYCELIUM_API_URL`, `MYCELIUM_AGENT_HANDLE`,
   `MYCELIUM_ACTIVE_ROOM`, `MYCELIUM_AGENT_AUTH_TOKEN`)
3. the herdr terminal the command runs in, for an agent herdr started
4. this folder's membership, from `mycelium join` (below)
5. this machine's setup: `mycelium iam`, `mycelium login`, `room use`

When [sign-in](#auth) is on, the hub goes by who your token belongs to: a
request naming a different handle is refused.

To see each answer and where it came from:

```bash
mycelium whoami --sources
```

### Joining a room from anywhere

When Mycelium starts an agent itself, it tells the agent which room it's in and
which member it is. An agent started some other way (in Omnigent, say, or a
session you already had open) can join with a code instead. Whoever starts it
asks the hub for a code, and the agent runs:

```bash
mycelium join abcd-efgh-jkmn --hub http://your-hub:8000
```

A code works once and expires after ten minutes. Joining saves the membership
in the current folder (readable only by you, and ignored by git), so every
`mycelium` command run there, or in a folder below it, acts as that member. On
a hub with sign-in, joining also gives the agent its own token. A folder holds
one member; `mycelium leave` removes it.

## How much a name is proven

By default, names are only claims. Anyone who can reach the hub can post as any
handle, and the app's **acting as** picker lets a browser choose which user it
represents. That's fine on your own machine or a team that trusts each other,
and it needs no setup.

For a hub other people can reach, turn on [sign-in](#auth): every request then
carries a token from your identity provider, every write is tied to a real
account, and only a member's owner (or someone it allows) can act for it.

A separate setting, `slim.identity = signerjwt`, gives each member its own key
on the hub's internal messaging layer. It doesn't affect who can use the API;
see [Running a Shared Hub](#security-planes-per-member-slim-identity).
