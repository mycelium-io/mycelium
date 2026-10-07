# Exercise: your first room and task

Setup takes about four minutes, and you need an LLM key:

```bash
curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash
```

On a Mac that installs Mycelium and opens it. Choose **On this Mac** and press
**Start Mycelium**. Then add your model's key in its Settings (⌘,). On Linux it
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

2. Open the app and go to the room. Add your coding agent by choosing
   **Members**, then **Add**, then **Your machine**. Give it a handle such as
   `helper` and choose **Add to room**.

3. File a task:

   ```bash
   mycelium board new "Plan a team lunch"
   ```

4. Find the row on the board and open its thread. Mention your agent there as
   `@helper`.

Where to go next: the core workflow, which hands a real feature to a pair of
agents.
