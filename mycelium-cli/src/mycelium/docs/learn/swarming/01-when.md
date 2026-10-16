# When a team beats a pair

A pair is the right shape for one coherent change, such as a feature in one
area, a bug or a refactor. A swarm is for work with **parts**. Parts are pieces
different agents can build at the same time, and each one can be checked on its
own.

Good fits:

- A feature that spans layers, such as an API, a screen, its tests and its
  docs.
- The same change in several separate places, such as three services or four
  clients.
- A spread of small, unrelated fixes from one list.

Poor fits:

- One change that touches everything at once, like a rename across the
  codebase.
- A bug you don't understand yet. Finding it is one thread of thought.
- Anything where the parts can't be judged until all of them exist.

Here's a rough test. If you can write down the parts and who'd take each before
anyone starts, swarm it. If you can't, give it to a pair.
