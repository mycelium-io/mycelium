# The Desktop App

The desktop app is the quickest way to get going. It runs everything Mycelium
needs on your computer, with no Docker and no setup in a terminal, and starts
your coding agents for you when you ask.

| Your computer | Download | Needs |
|---|---|---|
| Mac | **[Mycelium for Mac](https://github.com/mycelium-io/mycelium/releases/latest/download/Mycelium-macos-arm64.dmg)** | Apple silicon, macOS 13 or later |
| Linux (preview) | **[Linux AppImage](https://github.com/mycelium-io/mycelium/releases/latest/download/Mycelium-linux-x86_64.AppImage)** | x86-64, glibc 2.35 or later (Ubuntu 22.04, Fedora 36, Debian 12 or newer) |
| Windows (preview) | **[Windows installer](https://github.com/mycelium-io/mycelium/releases/latest/download/Mycelium-windows-x86_64-setup.exe)** | x64, Windows 10 or later |

The Linux and Windows builds are previews and get less testing than the Mac
build.

## Install

- **Mac:** drag **Mycelium** into **Applications** and open it. The first
  time, macOS asks whether to open an app from the internet. Choose **Open**.
- **Linux:** make the file executable
  (`chmod +x Mycelium-linux-x86_64.AppImage`) and run it.
- **Windows:** run the installer. It installs for you alone, with no
  administrator prompt. The installer isn't code-signed, so Windows asks before
  running it. Choose **More info**, then **Run anyway**.

The app then asks a few questions:

- **Where your rooms live.** **On this computer** runs a hub here. **On my
  team's hub** joins rooms that someone else runs. For that, paste the hub's
  address or open an invite link a teammate sent you.
- **A model.** The [engines](#engines) use it. You can add it later.
- **Agents on this computer.** It shows the agent CLIs it found and the folder
  agents may work in. It also asks whether herdr should bring your agents back
  after it restarts.
- **Usage stats.** These are off unless you tick the box. See
  [Metrics](#metrics) for what would be sent.

![The first step: where your rooms live](desktop-onboarding.png)

Your settings and rooms live in the `.mycelium` folder in your home folder. The
app writes nothing outside your home folder, and **What this sets up** lists
every change before you start.

> **A hub on this computer is yours alone.** It runs only while the app is
> running, and only this computer can reach it. To share rooms, run the hub on
> a server and have everyone choose **On my team's hub**. See
> [Hub & Spoke](#hub-and-spoke).

The app includes everything Mycelium runs, at versions tested together. It
doesn't include an agent CLI. Install the one you use, such as Claude Code,
Codex or OpenCode, and the app finds it.

## Adding and watching agents

In a room, open **Members**, press **Add** and pick **Your machine**. Start
from a role or write your own instructions, then press **Add to room**. The
agent opens in a herdr terminal and is already a member of the room. See
[Start Agents From the App](#machines).

To type to an agent, open the agents terminal. **terminal** in the bar at the
bottom of the window opens it, and so does **Open terminal** beside an agent on
**Machines**.

To watch an agent without leaving the room, open its terminal read-only:

- **Members:** click the agent.
- **Machines:** press **View** on its row.
- **The channel:** while it's responding, click its name on the "is
  responding" line. Rest the pointer on the name to see its last few lines.

The view says "Streamed from this machine. Nothing is sent to the hub." The app
reads the terminal from herdr itself. A key or private code on screen never
leaves your computer. For an agent on another computer, the view says where it
runs instead.

## The app's menu

Mycelium has an icon in the menu bar on a Mac, and in the system tray on Linux
and Windows. Closing the window leaves it running. **Quit Mycelium** stops the
hub. Agents keep running in herdr either way and pick up again when the hub is
back.

The menu shows whether each part of Mycelium is running. **Health check…** runs
the same checks as `mycelium doctor --mode desktop` and says what to do about
anything that's wrong. The menu also opens **Settings…** and the **Logs**, and
has **Check for Updates…**.

![The health check](desktop-health.png)

## Updates

The app checks for a new release when it opens and every few hours. It asks
before installing one, and it installs only an update the project signed.

herdr keeps running through an update, so your agents aren't interrupted. On a
Mac, macOS can then refuse the old herdr access to folders like Documents, and
commands there fail with "Operation not permitted". The app notices and asks
whether to restart herdr. Restarting stops the agents running in it. The ones
herdr may bring back reopen in their own conversations. Start the others again
from **Your agents…**.

**Settings → Version** switches to another release. To try the next version
early, turn on **Offer release candidates**. Going back to an older version
asks you twice, because rooms saved by a newer version may not open in an
older one.

## Logs

Both open from **Logs** in the menu:

- **App log** (`~/.mycelium/logs/desktop.log`). It records everything the app
  runs, and why a part of it stopped. Earlier runs are kept beside it.
- **Agent starts** (`~/.mycelium/runner/runner.log`). It records every agent a
  room asked this computer to start, and what happened. Look here first when an
  agent won't start.

## The command line

On an Apple silicon Mac, the install script installs the app and puts its
`mycelium` CLI on your path:

```bash
curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash
```

`mycelium desktop serve` runs the same hub without the window.
