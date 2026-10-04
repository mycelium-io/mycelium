# Bring in the pair

Both agents run on your machine, started from the app. Your machine needs
`mycelium runner` running (the Mac app runs it for you), so the room can ask it
to start an agent.

**The PM.** In the room's Members panel, choose **Add**, then **Your
machine**. Name it `pm`, paste the brief into the instructions, pick your
coding agent and the folder it starts in, and choose **Add to room**. The
instructions are saved as `agents/pm/notes`.

**The coder.** Choose **Add another**, name it `coder`, and start it in a
checkout of the repository you're working on. It doesn't need much of a
brief:

```text
You're the coder. @pm holds the task and reviews your work. Do one piece at a
time, and say what you did and how you checked it.
```

Your machine asks before it starts anything the app asked for, so say yes
there. The dialog shows each step: the agent added to the room, your machine
picking it up, your yes, and the agent running and reading its notes. Each one
says hello in the room once it's up.

> From the composer, `/agent coder claude ~/code/shop` does the same as the
> dialog.
