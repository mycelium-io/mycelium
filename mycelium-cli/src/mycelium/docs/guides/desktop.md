# The Mac App

Mycelium for Mac is the quickest way to get going. It runs everything Mycelium
needs on your Mac with no Docker and no setup in a terminal. It also starts
your coding agents for you when you ask.

**[Download Mycelium for Mac](https://github.com/mycelium-io/mycelium/releases/latest/download/Mycelium-macos-arm64.dmg)**
(Apple silicon, macOS 13 or later)

The same app runs on Linux and Windows, as a preview:

- **[Linux AppImage](https://github.com/mycelium-io/mycelium/releases/latest/download/Mycelium-linux-x86_64.AppImage)**
  (x86-64, glibc 2.35 or later: Ubuntu 22.04, Fedora 36, Debian 12 and
  newer). Make it executable (`chmod +x Mycelium-linux-x86_64.AppImage`) and
  run it. Nothing is installed.
- **[Windows installer](https://github.com/mycelium-io/mycelium/releases/latest/download/Mycelium-windows-x86_64-setup.exe)**
  (x64, Windows 10 or later). It installs for you alone, with no
  administrator prompt. It isn't code-signed yet, so the first time Windows
  asks: choose **More info**, then **Run anyway**.

Everything below works the same there. Where this page says "this Mac", read
"this computer", and ⌘ is Ctrl.

## Install

1. Open the download and drag **Mycelium** into **Applications**.
2. Open Mycelium from Applications. The first time, macOS asks whether to open
   an app downloaded from the internet. Choose **Open**.
3. A few short steps set it up:
   - **Where your rooms live.** **On this Mac** runs a hub on this Mac.
     **On my team's hub** joins rooms someone else runs. Paste the hub's
     address or open an invite link a teammate sent you.
   - **A model**, for a hub on this Mac. Pick a provider and paste its key. The
     [engines](#engines) think with it. You can skip this and add it later.
   - **Agents on this Mac.** This shows the agent CLIs it found and the folder
     that agents started from Mycelium may work in. It also asks whether herdr
     should bring your agents back after it restarts. That adds a hook to each
     agent CLI's settings, so it's your choice.
   - **Usage stats**, for a hub on this Mac. This decides whether the hub may
     send anonymous counts of tasks, flows and agents to an analytics address.
     It's off unless you tick it. Nothing is sent until an address is set in
     the hub's config (`telemetry.analytics_destination`), and the app doesn't
     set one. See [Metrics](#metrics) for exactly what would be sent.
   - **Ready to start.** This shows what you chose. Then press
     **Start Mycelium**.

![The first step: where your rooms live](desktop-onboarding.png)

Before you start, **What this sets up on your Mac** lists every change it
makes. `mycelium` and `herdr` are linked into `~/.local/bin` so agents can run
them, and your settings and rooms live in `~/.mycelium`. It needs no admin
password and writes nothing outside your home folder.

> **A hub on this Mac is yours alone.** It runs only while the app is running,
> and only this Mac can reach it, so teammates can't join rooms on it. To share
> rooms, run the hub on a server and have everyone choose **On my team's hub**.
> See [Hub & Spoke](#hub-and-spoke).

## What's inside

The app carries everything, pinned to versions tested together:

- the Mycelium hub and its UI;
- a [SLIM](#slim) node for the rooms' messages;
- [herdr](#herdr), where your agents run as terminals you can watch and type
  to;
- the `mycelium` CLI, which agents use to work in rooms;
- the [runner](#machines), which starts your agents and wakes them;
- Pi, which the engines think with, and the model that powers memory search so
  search works offline.

It doesn't include an agent CLI. Install the one you use, such as Claude Code,
Codex or OpenCode, and the app finds it.

## Adding agents

In a room, open **Members**, press **Add** and pick **Your machine**. Start
from a role or write your own instructions, then press **Add to room**. The
agent opens in a herdr terminal and is already a member of the room. The same
dialog adds engines, A2A services and coding agent sessions you already have
open. See [Start Agents From the App](#machines).

To watch or talk to an agent, use **Agents terminal** in the menu bar. You can
also open the **Machines** page and choose **Open terminal**.

## The menu bar

Mycelium lives in the menu bar while it runs. Closing the window leaves it
running, and **Quit Mycelium** stops the hub. Agents you started keep running
in herdr either way and pick up again when the hub is back.

The menu shows the state of the hub, the SLIM node and the runner. It also has
these items:

- **Open Mycelium**, **Agents terminal** and **Your agents…**
- **Start at login**
- **Health check…**, which shows each part the app runs and whether it's
  working. When something isn't, it says what to do. It runs the same checks as
  `mycelium doctor --mode desktop`.
- **Settings…** (⌘,), for where rooms live, starting at login, the
  [model](#models), the agents' folder and usage stats. **Save** restarts
  Mycelium with the change.
- **Check for Updates…**

![The health check](desktop-health.png)

## Updates

The app checks for a new release shortly after it opens and whenever you choose
**Check for Updates…**. If one is out, it asks before installing it and then
restarts. An update installs only if it carries the release's signature, so the
app never installs anything the project didn't publish.

## Logs

Everything the app runs writes to `~/.mycelium/logs/desktop.log`.

## The command line

The installer on the docs site installs the app too.
`curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash` puts it in
Applications, links its `mycelium` CLI into `~/.local/bin` and opens it.
`mycelium desktop serve` runs the same hub without the window.
