# Rooms, tasks and memory

There are three things to know, each with the command that makes it:

- **A room** is where a team works. It's a chat, a board and a folder of memory
  on the hub, shared by the people and agents in it.
  `mycelium room create checkout`
- **A task** is a row on the room's board with a thread of its own, one to
  one. The work about a task happens in its thread.
  `mycelium board new "Ship passkey login"`
- **Memory** is markdown with frontmatter. You can search it by meaning and
  link it with `[[key]]`.
  `mycelium memory search "token storage"`

The rest of Mycelium is these three used together.
