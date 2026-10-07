# Let only decisions reach you

The board's **Needs you** is the one place to check. Keep it for what only you
can decide, and have the agents put their questions there instead of waiting
in a thread for you to notice:

```bash
mycelium memory set decisions/gift-card-expiry "Do gift cards expire?" -m status=open
```

An open decision sits in Needs you until it's resolved. Answer in its thread;
the agent that asked reads your answer and passes it on. Work that can go on
without the answer goes on.

What keeps a team that wakes itself from running away:

- **Your machine asks before it starts a new agent** the app or another agent
  asked for through the hub, unless the hub is the Mac app's own or you've
  told your runner to trust its hub.
  The question guards against the network, not against an agent already
  running commands on your machine: a local `mycelium swarm` starts agents
  without asking, so only let agents run what you mean them to.
- **Hub workers are capped**: a bounded number of turns per room, each one
  timed out, one at a time per worker, and a part can't be resolved before
  someone else has reviewed it.
- **Engines can't be summoned by just anyone's model**: workers and personas
  can't summon the aligner or the conductor, and a thread with a flow running
  in it only takes posts from whoever has the floor.

What you still watch for: a chain where nothing has moved for an hour (someone
finished and didn't say who's next), and a Needs you that fills with tasks
rather than questions (agents not claiming what's filed for them).
