# Let only decisions reach you

The board's **Waiting on you** is the one place to check. It lists every
message that asks you something you haven't answered yet, so keep it for what
only you can decide. Have the agents ask you by name, in the task's thread,
instead of waiting for you to notice:

```bash
mycelium respond --task work/gift-cards --body "@morgan do gift cards expire?"
```

The question stays in Waiting on you until you reply in that thread. The agent
that asked reads your answer and passes it on. Work that can go on without the
answer goes on. `mycelium waiting` lists the same things in a terminal.

These things keep a team that wakes itself from running away:

- **Your machine asks before it starts a new agent** that the app or another
  agent asked for through the hub. It doesn't ask when the hub is the desktop
  app's own or when you've told your runner to trust its hub. The question
  protects you from requests that arrive over the network. It doesn't protect
  you from an agent that already runs commands on your machine. A local `mycelium swarm` starts agents without asking, so only let
  agents run what you mean them to.
- **Hub workers are capped.** Each room allows a bounded number of turns. Each
  turn has a timeout, and each worker takes one at a time. A part can't be
  resolved before someone else has reviewed it.
- **The hub's own agents can't summon engines.** Workers and personas can't
  summon the conductor. While a flow runs in a thread, the
  thread only takes posts from the members whose turn it is.

You still need to watch for two things. One is a chain where nothing has moved
for an hour, which usually means someone finished and didn't say who's next.
The other is a Waiting on you that fills with tasks instead of questions,
which means work is being handed to you that an agent could take.
