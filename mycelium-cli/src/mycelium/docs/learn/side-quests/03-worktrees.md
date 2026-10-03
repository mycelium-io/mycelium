# A worktree for each

A git worktree is a second folder for the same repository, on its own branch.
Give each side quest one:

```bash
git worktree add ../shop-flaky-test -b fix/flaky-test
```

Then start the side-quest agent in that folder: in the Members panel choose
**Add**, then **Your machine**, name it (`fixer`), and set its folder to the
worktree. The folder has to be inside one your runner lets agents start in
(its `--root`).

The agent works on its own branch, and the fix lands as its own small pull
request. When that's merged, remove the worktree:

```bash
git worktree remove ../shop-flaky-test
```

> Hub workers (the agents a swarm runs on the hub) already get a worktree and
> a branch of their own, so this step is only for agents on your machine.
