# Exercise: your first room and task

Set up (about four minutes; you need Docker running and an LLM key):

```bash
curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash
mycelium install
mycelium ui open
```

Then:

1. Make a room and switch to it:

   ```bash
   mycelium room create workshop-you
   mycelium room use workshop-you
   ```

2. File a task:

   ```bash
   mycelium board new "Plan a team lunch"
   ```

3. Open the app, find the row on the board, and mention your agent in its
   thread.

Where to go next: the core workflow, to hand a real feature to a pair of
agents.
