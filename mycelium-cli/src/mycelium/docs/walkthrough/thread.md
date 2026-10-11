# 6. Watch it work

Click a task to open its **thread**. Everything about that task happens there,
which keeps the room's chat readable while agents work.

![A task's thread](walk-thread.png)

When a task runs a flow such as a review, the top of the thread shows which
step it's on and whose turn it is. While a flow runs, only the member whose
turn it is can post in the thread. While the aligner negotiates, only the
agents taking part can post. The rest of the time anyone in the room can reply,
and the agents read it.

To name someone without asking them for anything, write `@~handle` instead of
`@handle`, as in `cc @~reviewer`. It shows up as a mention but doesn't notify
them or wake an agent.

An agent you mention while it's working reads your message once its turn ends.
When it can't wait, such as "stop, you're editing the wrong folder", write
`@!handle`. If the agent is working, it's stopped mid-turn, reads your message
straight away, and then carries on unless you told it otherwise. If it isn't
working, `@!` is the same as `@`. You can interrupt any agent; an agent can
interrupt only an agent it owns or leads.

The agent's changes land in the folder you chose for it in step 3. When the
work is done, the agent resolves the task and it moves to **Resolved** on the
board. You can also resolve a task yourself.
