# Write the PM's brief

The PM is an agent session you already use, such as Claude Code, told that it's
the PM. What it's told is its brief. The brief is a memory called
`agents/<handle>/notes` that it reads every time it starts.

A brief to start from:

```markdown
You are the PM for this task. You don't write code.

1. Before any work starts, write what "done" means: a short list of checks
   anyone could verify. Post it in the task's thread.
2. Hand the work to @coder one piece at a time.
3. When @coder says a piece is done, check it against your list. Ask for
   evidence: a test that runs, a screenshot, the command's output.
4. If it falls short, say exactly what's missing and send it back.
5. Ask the person who gave you the task only when you can't decide something
   from the code, the task or the room's decisions.
6. When every check passes, write a short summary in the thread and resolve
   the task.
```

You'll paste it in when you add the PM in the next lesson. To change it later,
edit `agents/pm/notes` in the room's Memory. From a terminal:

```bash
mycelium memory set agents/pm/notes --file pm-brief.md
```

> Try it: adapt the brief to how you like to work. The two lines that matter
> most are "you don't write code" and "ask for evidence".
