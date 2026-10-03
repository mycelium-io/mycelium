# Side quests

> A sketch. It will change as we learn more.

While a pair works on the main thing, small things come up: a flaky test, a
flag to rename, a doc to fix. They shouldn't interrupt the pair, and they
shouldn't touch the coder's checkout.

## One task each

Give each one its own task, from the room's chat:

```
/task Fix the flaky checkout test @fixer
```

It's a row and a thread of its own. When it's done it's resolved and out of
the way, with nothing to clean up elsewhere.

## Each in its own worktree

Two agents in one checkout step on each other: one switches branches under
the other, or commits the other's half-finished change. Give a side quest its
own git worktree, so it works on its own branch in its own folder and lands as
its own small pull request:

```bash
git worktree add ../shop-flaky-test -b fix/flaky-test
```

Then start the side-quest agent in that folder. The folder has to be inside
the folders your machine's [runner](#machines) lets agents start in.

When it's merged, remove the worktree:

```bash
git worktree remove ../shop-flaky-test
```

Agents that run on the hub (workers) already get a worktree of their own for
each turn, so this step is only for agents on your machine.
