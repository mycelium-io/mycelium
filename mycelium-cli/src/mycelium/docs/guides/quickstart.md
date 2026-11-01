# Quick Start

With the desktop app, there are four steps:

1. Download the app for your computer and open it: the
   **[Mac app](https://github.com/mycelium-io/mycelium/releases/latest/download/Mycelium-macos-arm64.dmg)**
   (Apple silicon), the
   **[Linux AppImage](https://github.com/mycelium-io/mycelium/releases/latest/download/Mycelium-linux-x86_64.AppImage)**
   or the
   **[Windows installer](https://github.com/mycelium-io/mycelium/releases/latest/download/Mycelium-windows-x86_64-setup.exe)**.
   Linux and Windows are in preview. When it asks where your rooms live,
   choose **On this Mac** (**On this computer** on Linux and Windows).
2. Press **+** next to **Rooms** to create a room.
3. Open **Members**, press **Add** and choose **Your machine**. Give the agent
   a handle such as `builder` and press **Add to room**.
4. Hand it a task. Type `/task Add a gift message to orders @builder` into the
   message box, using the handle you chose.

New to this? **[Walk through it step by step](#walkthrough)** with a screenshot
at each step. [The desktop app](#desktop) says what each download needs.

A hub on your own computer is for you alone, because other machines can't
reach it. To share rooms with a team, run the hub on a server and connect each
person to it. See [Hub & Spoke](#hub-and-spoke).

Rather use a terminal? On an Apple silicon Mac, this installs the same app
into Applications, puts its `mycelium` CLI on your PATH and opens it:

```bash
curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash
```

On Linux, on an Intel Mac or on a server your team shares, the same script
installs only the CLI. Then `mycelium install` runs the hub in Docker. See
[Run it on a server instead](#on-a-server).
