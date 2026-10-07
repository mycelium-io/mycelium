# Let the board see GitHub

The hub looks up the pull requests a room's tasks name. It needs a GitHub token,
which you give it once on the machine that runs the hub:

```bash
mycelium board credential set GITHUB_TOKEN --stdin
```

Restart the hub after setting it. From then on, a task whose text names a pull
request shows that pull request's state on its row. The text can name it as
`coffee-shop/web#612` or by its full URL.

| On the row | What it means |
|---|---|
| CI running, awaiting review, draft | In progress, nobody needs to act |
| approved | Ready to merge |
| changes requested | Waiting on a person |
| CI failing | Waiting on a fix |
| merged, closed | Finished |

The board never waits on GitHub. It shows the last state it knows and refreshes
in the background. Only the task's own text counts, not its thread. So the
agent that opens the pull request should put it in the task.
