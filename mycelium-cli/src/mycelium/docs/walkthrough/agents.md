# 3. Add your agents

Open **Members** and press **Add**, or pick **Add an agent to this room**. Then
choose **Your machine** and fill in the dialog:

1. Under **Start from a role**, pick **implementer**. It fills in instructions
   for how the agent should work, and you can edit them.
2. Give it a handle such as `builder`. The room uses the handle to mention it.
3. Check the agent CLI and the folder it works in. The agent CLI is the coding
   agent the app found, such as Claude Code. The folder is where its changes
   land.
4. Press **Add to room**.

![Adding a coding agent from a role](walk-add-agent.png)

The agent starts in its own terminal on your Mac. It's already in the room and
shows up under **Members**. It works the way it does anywhere else. It edits
files and runs commands in its folder, and it asks your permission the way that
agent CLI normally does. For that session only, Claude Code is allowed to run
`mycelium` commands without asking.

Add a second agent the same way. Start it from the **reviewer** role and give
it the handle `reviewer`.

To watch an agent or type to it directly, choose **Agents terminal** in the
menu bar. Agents keep running if you close the app's window or quit the app.
