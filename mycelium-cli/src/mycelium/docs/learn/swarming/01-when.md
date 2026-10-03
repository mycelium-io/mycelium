# When a team beats a pair

A pair is the right shape for one coherent change: a feature in one area, a
bug, a refactor. A swarm is for work with **parts**: pieces different agents
can build at the same time, each checkable on its own.

Good fits:

- A feature that spans layers: an API, a screen, its tests, its docs.
- The same change in several separate places: three services, four clients.
- A spread of small, unrelated fixes from one list.

Poor fits:

- One change that touches everything at once (a rename across the codebase).
- A bug you don't understand yet. Finding it is one thread of thought.
- Anything where the parts can't be judged until all of them exist.

A rough test: if you can write down the parts and who'd take each before
anyone starts, swarm it. If you can't, give it to a pair.
