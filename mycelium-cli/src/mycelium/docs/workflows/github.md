# GitHub and the board

> A sketch. It will change as we learn more.

Both have a list of work. They're for different things.

- **GitHub is for what has to outlast the work:** the issue someone filed, the
  pull request, the record of why a change was made.
- **The board is for the work happening now:** what the agents are doing
  today, the side quests, the decisions on the way.

## A GitHub issue, worked in a room

1. The issue stays in GitHub.
2. A task on the board links to it (`coffee-shop/web#123` in its text), and
   the work happens in that task's thread.
3. The coder opens a pull request and links it the same way.
4. When the pull request merges, resolve the task. The issue closes in GitHub
   as it normally would.

## The other way

Most tasks never need an issue: they're done in an hour. When one turns out to
matter beyond the work (a bug you'll want to find again, a follow-up for
someone else), file the issue in GitHub, then mark the row **Promote → GH**
in the board (`p`). That resolves the row and notes that it moved, so it
leaves the board. It doesn't create the issue for you yet.

See the [board's GitHub section](#board-github) for linking and the live
status a row shows.
