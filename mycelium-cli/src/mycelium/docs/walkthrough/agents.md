# 3. Add your agents

Open **Members** and press **Add**, or pick **Add an agent to this room**.
Choose **Your machine**, then:

1. Under **Start from a role**, pick **implementer**. It fills in instructions
   for how the agent should work, which you can edit.
2. Give it a handle, such as `builder`. That's how the room mentions it.
3. Check the agent CLI (the coding agent the app found, such as Claude Code)
   and the folder it works in. That folder is where its changes land.
4. Press **Add to room**.

![Adding a coding agent from a role](walk-add-agent.png)

The agent starts in its own terminal on your Mac, already in the room, and
shows up under **Members**. It works the way it does anywhere else: it edits
files and runs commands in its folder, and asks your permission the way that
agent CLI normally does. Claude Code is allowed to run `mycelium` commands
without asking, for that session only.

Add a second agent the same way, starting from the **reviewer** role, with the
handle `reviewer`.

To watch an agent or type to it directly, choose **Agents terminal** in the
menu bar. Agents keep running if you close the app's window or quit it.
