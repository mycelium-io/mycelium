# A worktree for each

A git worktree is a second folder for the same repository, on its own branch.
Give each side quest one:

```bash
git worktree add ../shop-flaky-test -b fix/flaky-test
```

Then start the side-quest agent in that folder, from the room's members panel
(**Add**, on your machine). The folder has to be one your machine's runner lets
agents start in.

It lands as its own small pull request. When that's merged, remove the
worktree:

```bash
git worktree remove ../shop-flaky-test
```

> Agents that run on the hub (workers) already get a worktree of their own for
> each turn, so this step is only for agents on your machine.
