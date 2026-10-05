# Quick Start

On a Mac, four steps:

1. **[Download Mycelium for Mac](https://github.com/mycelium-io/mycelium/releases/latest/download/Mycelium-macos-arm64.dmg)**,
   open it, and choose **On this Mac**.
2. Press **+** next to **Rooms** to create a room.
3. Open **Members**, press **Add**, and add a coding agent from **Your
   machine**.
4. Hand it a task: type `/task Add a gift message to orders @builder` into
   the message box.

New to this? **[Walk through it step by step](#walkthrough)**, with a
screenshot at each step.

Rather use a terminal? This installs the same app into Applications, puts
its `mycelium` CLI on your PATH, and opens it:

```bash
curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash
```

On Linux or a server your team shares, the same installer installs the CLI,
which runs the hub in Docker:

```bash
curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash
mycelium install
```

See [Run it on a server instead](#on-a-server) for the rest.
