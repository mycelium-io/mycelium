# Work a GitHub issue in a room

1. **The issue stays in GitHub.** File a task for it and put the issue's link
   in the text, so anyone can get back to it:

   ```text
   /task Fix tax rounding on receipts github.com/coffee-shop/web/issues/118 @coder
   ```

2. **The work happens in the task's thread.**
3. **The coder opens a pull request** that says `Fixes #118`, and adds it to
   the task's text, so the row follows it.
4. **When the pull request merges, resolve the task.** GitHub closes the issue
   from the pull request, as it normally would.

> A bare `#118` typed into a new task means something else: the task is
> blocked by #118. Use the full link to point at an issue.
