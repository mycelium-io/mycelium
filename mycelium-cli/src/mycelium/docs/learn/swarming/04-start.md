# Start it, and where it runs

From the app: type the task into the board's **Add a task…** and press
**Swarm** (or Ctrl-Enter). The dialog asks how many agents (two to five) and,
when one of your machines is connected, where they run:

- **On the hub** (the default): the hub's own workers. Give it the
  repository's URL and the hub clones it; each worker gets its own branch and
  worktree of the clone.
- **On your machine:** your own agent CLI, each in its own pane, in the folder
  you pick. Tick "Give each agent its own git worktree" so they never share a
  checkout. Unless the hub is the Mac app's own, your machine asks you before
  it starts them.

Or from a terminal in the repository, in the room you work in:

```bash
mycelium swarm "Add CSV export for orders. Parts: ..." -n 3 --worktree
```

That starts the members on your machine (it needs herdr running). Add
`--server --repo <url>` to run them on the hub instead. From the terminal a
team can be two to eight.

Your machine is the better choice for real code you'll keep working on: the
agents work in your repository, with your tools. The hub is for when you want
the team to run without your laptop.
