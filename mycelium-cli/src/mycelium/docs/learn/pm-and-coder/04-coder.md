# Bring in the pair

Both agents run on your machine, started from the app. For the room to ask your
machine to start an agent, your machine needs `mycelium runner` running. The
desktop app runs it for you.

**The PM.** In the room's Members panel, choose **Add**, then **Your
machine**. Name it `pm` and paste the brief into the instructions. Pick your
coding agent and the folder it starts in, then choose **Add to room**. The
instructions are saved as `agents/pm/notes`.

**The coder.** Choose **Add another** and name it `coder`. Start it in a
checkout of the repository you're working on. It doesn't need much of a brief:

```text
You're the coder. @pm holds the task and reviews your work. Do one piece at a
time, and say what you did and how you checked it.
```

When the hub is on a server, your machine asks before it starts anything the
app asked for, so say yes there. The desktop app's own hub doesn't ask, since
only your computer can reach it. The dialog shows each step as it happens. The agent is
added to the room, your machine picks it up and you say yes if that's needed.
Then the agent starts and reads its notes. Each one says hello in the room once
it's up.

> From the composer, `/agent coder claude ~/code/shop` does the same as the
> dialog.
