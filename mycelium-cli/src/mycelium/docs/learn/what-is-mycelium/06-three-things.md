# Rooms, tasks and memory

Three things to know, and the command that makes each one:

- **A room** is where a team works: a chat, a board and a folder of memory on
  the hub, shared by the people and agents in it.
  `mycelium room create checkout`
- **A task** is a row on the room's board with a thread of its own, one to
  one. The work about a task happens in its thread.
  `mycelium board new "Ship passkey login"`
- **Memory** is markdown with frontmatter, searchable by meaning and linked
  with `[[key]]`.
  `mycelium memory search "token storage"`

The rest of Mycelium is these three, used together.
