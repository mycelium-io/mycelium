# The Desktop App

The desktop app is the quickest way to get going. It runs everything Mycelium
needs on your computer, with no Docker and no setup in a terminal. It also
starts your coding agents for you when you ask.

| Your computer | Download | Needs |
|---|---|---|
| Mac | **[Mycelium for Mac](https://github.com/mycelium-io/mycelium/releases/latest/download/Mycelium-macos-arm64.dmg)** | Apple silicon, macOS 13 or later |
| Linux (preview) | **[Linux AppImage](https://github.com/mycelium-io/mycelium/releases/latest/download/Mycelium-linux-x86_64.AppImage)** | x86-64, glibc 2.35 or later (Ubuntu 22.04, Fedora 36, Debian 12 or newer) |
| Windows (preview) | **[Windows installer](https://github.com/mycelium-io/mycelium/releases/latest/download/Mycelium-windows-x86_64-setup.exe)** | x64, Windows 10 or later |

The Linux and Windows builds are previews: every release builds them, and
they get less testing than the Mac app.

## Install

- **Mac:** open the download and drag **Mycelium** into **Applications**, then
  open it from there. The first time, macOS asks whether to open an app
  downloaded from the internet. Choose **Open**.
- **Linux:** make the file executable
  (`chmod +x Mycelium-linux-x86_64.AppImage`) and run it. It runs from that one
  file, so there's nothing to install.
- **Windows:** run the installer. It installs for you alone, with no
  administrator prompt. The installer isn't code-signed, so the first time
  Windows asks before running it: choose **More info**, then **Run anyway**.

The app then walks you through a few short steps. The app calls your computer
"this Mac" on a Mac and "this computer" elsewhere; this page says "this
computer".

- **Where your rooms live.** **On this computer** runs a hub here. **On my
  team's hub** joins rooms someone else runs. Paste the hub's address or open
  an invite link a teammate sent you.
- **A model**, for a hub on this computer. Pick a provider and paste its key.
  The [engines](#engines) think with it. You can skip this and add it later.
- **Agents on this computer.** This shows the agent CLIs it found and the
  folder that agents started from Mycelium may work in. It also asks whether
  herdr should bring your agents back after it restarts. That adds a hook to
  each agent CLI's settings, so it's your choice.
- **Usage stats**, for a hub on this computer. This decides whether the hub
  may send anonymous counts of tasks, flows and agents to an analytics
  address. It's off unless you tick it. Nothing is sent until an address is
  set in the hub's config (`telemetry.analytics_destination`), and the app
  doesn't set one. See [Metrics](#metrics) for exactly what would be sent.
- **Ready to start.** This shows what you chose. Then press
  **Start Mycelium**.

![The first step: where your rooms live](desktop-onboarding.png)

Before you start, **What this sets up** lists every change it makes. Your
settings and rooms live in `~/.mycelium` (on Windows, `.mycelium` in your user
folder). On a Mac or Linux, `mycelium` and `herdr` are linked into
`~/.local/bin` so agents can run them; on Windows, the app adds its own folder
to your PATH, so agents and the terminals you open next can run them. It needs
no administrator password and writes nothing outside your home folder.

> **A hub on this computer is yours alone.** It runs only while the app is
> running, and only this computer can reach it, so teammates can't join rooms
> on it. To share rooms, run the hub on a server and have everyone choose
> **On my team's hub**. See [Hub & Spoke](#hub-and-spoke).

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

To watch or talk to an agent, open the agents terminal: **terminal** in the
bar at the bottom of the window, **Agents terminal** on the home screen or in
the app's menu, or **Open terminal** beside an agent on the **Machines** page.

## The app's menu

While it runs, Mycelium has an icon in the menu bar on a Mac, and in the
system tray on Linux and Windows. Closing the window leaves it running, and
**Quit Mycelium** stops the hub. Agents you started keep running in herdr
either way and pick up again when the hub is back.

The menu shows the state of the hub, the SLIM node and the runner. It also has
these items:

- **Open Mycelium**, **Agents terminal** and **Your agents…**
- **Start at login**
- **Health check…**, which shows each part the app runs and whether it's
  working. When something isn't, it says what to do. It runs the same checks as
  `mycelium doctor --mode desktop`.
- **Logs**, which opens the app's log, the runner's log or the folder they're
  in. See [Logs](#logs).
- **Settings…** (⌘, on a Mac, Ctrl+, elsewhere), for where rooms live, starting at login, the
  [model](#models), the agents' folder and usage stats. **Save** restarts
  Mycelium with the change.
- **Check for Updates…**

![The health check](desktop-health.png)

## Updates

The app checks for a new release shortly after it opens, every few hours while
it runs, and whenever you choose **Check for Updates…**. If one is out, it asks
before installing it. While you haven't installed it yet, the app's header
shows **Update available**, which asks the same question. Once you say yes, a
small window shows the download until the app restarts into the new version.
An update installs only if it carries the release's signature, so the app
never installs anything the project didn't publish.

## Logs

Two logs say what went wrong. Both open from **Logs** in the menu, in whatever
opens log files on your computer (Console, on a Mac).

- **App log** (`~/.mycelium/logs/desktop.log`): everything the app runs, and
  why a part of it stopped.
- **Agent starts** (`~/.mycelium/runner/runner.log`): every agent a room asked
  this computer to start, and whether it started, is waiting for your yes, or
  failed and why. Look here first when an agent won't start. Older entries are
  in `runner.log.1` to `runner.log.3` beside it.

## The command line

On an Apple silicon Mac, the installer on the docs site installs the app too.
`curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash` puts it in
Applications, links its `mycelium` CLI into `~/.local/bin` and opens it.
`mycelium desktop serve` runs the same hub without the window.
