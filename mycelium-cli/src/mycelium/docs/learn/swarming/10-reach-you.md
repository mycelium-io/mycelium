# Let only decisions reach you

The board's **Needs you** is the one place to check. Keep it for what only you
can decide. Have the agents put their questions there instead of waiting in a
thread for you to notice:

```bash
mycelium memory set decisions/gift-card-expiry "Do gift cards expire?" -m status=open
```

An open decision sits in Needs you until it's resolved. Answer in its thread.
The agent that asked reads your answer and passes it on. Work that can go on
without the answer goes on.

These things keep a team that wakes itself from running away:

- **Your machine asks before it starts a new agent** that the app or another
  agent asked for through the hub. It doesn't ask when the hub is the desktop
  app's own or when you've told your runner to trust its hub. The question guards
  against the network, not against an agent already running commands on your
  machine. A local `mycelium swarm` starts agents without asking, so only let
  agents run what you mean them to.
- **Hub workers are capped.** Each room allows a bounded number of turns. Each
  turn has a timeout, and each worker takes one at a time. A part can't be
  resolved before someone else has reviewed it.
- **Engines can't be summoned by just anyone's model.** Workers and personas
  can't summon the aligner or the conductor. A thread with a flow running in it
  only takes posts from whoever has the floor.

You still need to watch for two things. One is a chain where nothing has moved
for an hour, which usually means someone finished and didn't say who's next.
The other is a Needs you that fills with tasks instead of questions, which
means agents aren't claiming what's filed for them.
