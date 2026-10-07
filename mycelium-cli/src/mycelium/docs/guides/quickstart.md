# Quick Start

On a Mac with Apple silicon, there are four steps:

1. **[Download Mycelium for Mac](https://github.com/mycelium-io/mycelium/releases/latest/download/Mycelium-macos-arm64.dmg)**
   and open it. When it asks where your rooms live, choose **On this Mac**.
2. Press **+** next to **Rooms** to create a room.
3. Open **Members**, press **Add** and choose **Your machine**. Give the agent
   a handle such as `builder` and press **Add to room**.
4. Hand it a task. Type `/task Add a gift message to orders @builder` into the
   message box, using the handle you chose.

On Linux or Windows the same four steps work with the app's preview builds:
the **[Linux AppImage](https://github.com/mycelium-io/mycelium/releases/latest/download/Mycelium-linux-x86_64.AppImage)** or the
**[Windows installer](https://github.com/mycelium-io/mycelium/releases/latest/download/Mycelium-windows-x86_64-setup.exe)**. There, the
first screen says **On this computer**.

New to this? **[Walk through it step by step](#walkthrough)** with a screenshot
at each step.

A hub on your Mac is for you alone, because other machines can't reach it. To
share rooms with a team, run the hub on a server and connect each person to
it. See [Hub & Spoke](#hub-and-spoke).

Rather use a terminal? This installs the same Mac app into Applications, puts
its `mycelium` CLI on your PATH and opens it:

```bash
curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash
```

The Mac app is built for Apple silicon only. On a Linux or Windows desktop, the
same app is in preview: see [the desktop app](#desktop) for the downloads. On an
Intel Mac or on a server your team shares, the script installs the CLI instead.
Then `mycelium install` runs the hub in Docker. See
[Run it on a server instead](#on-a-server).
