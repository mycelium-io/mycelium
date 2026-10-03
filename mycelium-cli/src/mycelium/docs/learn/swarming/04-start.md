# Start it, and where it runs

From a terminal in the repository, in the room you work in:

```bash
mycelium swarm "Add CSV export for orders. Parts: ..." -n 3 --worktree
```

The members are your own agent CLI, each in its own pane on your machine.
`--worktree` gives each one its own git worktree, so they never share a
checkout.

Or from the app: type the task in the board's capture bar and press **Swarm**.
The dialog asks how many agents and where they run:

- **On your machine:** your own agent CLI, the same as the command above. Your
  machine asks you before it starts them.
- **On the hub:** the hub's own workers, which can clone a repository for the
  team (`--server --repo <url>` from the command line).

Your machine is the better default for real code: the agents work in your
repository, with your tools. The hub is for when you want the team to run
without your laptop.
