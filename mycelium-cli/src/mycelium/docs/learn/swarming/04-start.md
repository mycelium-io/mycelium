# Start it, and where it runs

From the app, type the task into the board's **Add a task…** and press
**Swarm** or Ctrl-Enter. The dialog asks how many agents you want, from two to
five. When one of your machines is connected, it also asks where they run:

- **On the hub** (the default). The team is the hub's own workers. Give it the
  repository's URL and the hub clones it. Each worker gets its own branch and
  worktree of the clone.
- **On your machine.** The team is your own agent CLI, each in its own pane, in
  the folder you pick. Tick "Give each agent its own git worktree" so they
  never share a checkout. Unless the hub is the Mac app's own, your machine
  asks you before it starts them.

Or run it from a terminal in the repository, in the room you work in:

```bash
mycelium swarm "Add CSV export for orders. Parts: ..." -n 3 --worktree
```

That starts the members on your machine, which needs herdr running. Add
`--server --repo <url>` to run them on the hub instead. From the terminal a
team can have two to eight members.

Your machine is the better choice for real code you'll keep working on, because
the agents work in your repository with your tools. The hub is for when you
want the team to run without your laptop.
