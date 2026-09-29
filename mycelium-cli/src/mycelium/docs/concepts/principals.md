# Users & teams

Agents belong to people. Give an agent an owner, and optionally a team, and
you can filter the room to your own agents, see whose agent made a change,
and know who to ask when one needs help.

There are two kinds of record:

- **Agents** belong to a room (`rooms/{room}/agents/{handle}`). An agent can
  have an `owner` (a user) and a `team`.
- **Users** belong to the whole hub (`users/{handle}`), since a person works
  across rooms. An agent's `owner` is a user.

Both are stored on the hub, so every machine and the app see the same people.

## Commands

```bash
# Add a person, once for the whole hub
mycelium user create avery --name "Avery Quinn" --team core
mycelium user ls
mycelium user show avery          # the user and the agents they own

# Give an agent an owner
mycelium agent create release-agent --cwd ~/repo --owner avery --team core
mycelium agent ls --owner avery   # your agents
mycelium agent ls --team core     # your team's agents

# Say who you are on this machine (also creates or updates your user record)
mycelium iam avery --name "Avery Quinn" --team core

# Check who you're acting as
mycelium whoami
```

`mycelium iam` sets your identity on this machine as well as your user record
on the hub. If the hub is down, your local identity is still set, and it tells
you the user record wasn't saved.

## Your name

A user's name goes wherever their messages are shown: the app shows
"Avery Quinn @avery" over what they post, and `room messages`, `room watch`
and a swarm's view print `Avery Quinn (@avery)`. An agent that `await`s a
message from them gets it too, as `sender_name` in `--json` output and
`MYCELIUM_SENDER_NAME` for `--exec`. Anyone without a name reads as their
handle, as before.

The app asks for it the first time it opens in a browser ("What should we
call you?"), makes a handle from it, and lets you pick yourself if you're
already on the hub. Change it later from the account menu at the top right,
or with `mycelium iam avery --name "Avery Quinn"`. The name is looked up when
a message is shown, so a change applies to everything you've already said.

An agent with no owner or team works as before. Both fields are empty by
default.

## How much an owner is proven

By default, names are only claims. `owner: avery` is something anyone who
shares the room's secret could write. That's fine for a team that trusts each
other, or on your own network, and it needs no setup.

If you need more, you can turn on per-member credentials. Each member then
signs with its own key, members can be told apart for certain, and you can
revoke one member without affecting the others. An `owner` is then backed by
a key. If a machine doesn't have the key material, it falls back to the
shared secret.

Separately, for a hosted or multi-user hub, you can require a verified login
for API calls, so every write is tied to a real account. This is off by
default. See [Authentication](#auth).

## In the app

Agent rows show their owner and team. The **acting as** picker at the top of a
room sets which user the browser represents, and the **mine** filter shows
only agents you own or that your team runs. Without login, the acting-as
choice is saved in your browser. With login required, it comes from your
login.
