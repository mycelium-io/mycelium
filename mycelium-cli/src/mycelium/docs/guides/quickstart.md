# Quick Start

On a Mac with Apple silicon, four steps:

1. **[Download Mycelium for Mac](https://github.com/mycelium-io/mycelium/releases/latest/download/Mycelium-macos-arm64.dmg)**,
   open it, and choose **On this Mac** when it asks where your rooms live.
2. Press **+** next to **Rooms** to create a room.
3. Open **Members**, press **Add**, choose **Your machine**, give the agent a
   handle such as `builder`, and press **Add to room**.
4. Hand it a task: type `/task Add a gift message to orders @builder` into
   the message box, using the handle you chose.

New to this? **[Walk through it step by step](#walkthrough)**, with a
screenshot at each step.

A hub on your Mac is for you alone: other machines can't reach it. To share
rooms with a team, run the hub on a server instead and connect each person to
it. See [Hub & Spoke](#hub-and-spoke).

Rather use a terminal? This installs the same Mac app into Applications, puts
its `mycelium` CLI on your PATH, and opens it:

```bash
curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash
```

On Linux, on an Intel Mac (the Mac app is built for Apple silicon only), or on
a server your team shares, the same script installs the CLI, and
`mycelium install` then runs the hub in Docker. See
[Run it on a server instead](#on-a-server).
