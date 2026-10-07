# Exercise: your first room and task

Set up (about four minutes; you need an LLM key):

```bash
curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash
```

On a Mac that installs Mycelium and opens it: choose **On this Mac**, press
**Start Mycelium**, and add your model's key in its Settings (⌘,). On Linux it
installs the CLI, and the hub runs in Docker:

```bash
mycelium install
mycelium ui open
```

Then:

1. Make a room and switch to it:

   ```bash
   mycelium room create workshop-you
   mycelium room use workshop-you
   ```

2. Open the app, go to the room, and add your coding agent: in **Members**,
   choose **Add**, then **Your machine**, give it a handle such as `helper`,
   and choose **Add to room**.

3. File a task:

   ```bash
   mycelium board new "Plan a team lunch"
   ```

4. Find the row on the board, open its thread, and mention your agent there
   (`@helper`).

Where to go next: the core workflow, to hand a real feature to a pair of
agents.
