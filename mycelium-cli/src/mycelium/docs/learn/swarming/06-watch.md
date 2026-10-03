# Watch and steer

The task's thread shows the kickoff: each member checking in, then the lead's
split. Each part lands on the board as a task of its own, marked as part of
the original, with its own thread where it's built and reviewed.

If you started the swarm from a terminal, that terminal shows the
conversation as it happens, across the task and every part, with long
messages cut short and the final result printed in full. Press Ctrl-C to stop
watching. A team on the hub keeps going; agents on your machine need
`mycelium runner` (or `mycelium herdr sync`) running to keep hearing their
turns.

To steer:

- **Before the split lands**, answer in the task's thread if the members'
  offers miss the point. The lead reads it before splitting.
- **On a part**, write in that part's thread. Its builder and its reviewer
  both read it.
- **At the end**, read the lead's combined result in the task's thread before
  you merge anything.
