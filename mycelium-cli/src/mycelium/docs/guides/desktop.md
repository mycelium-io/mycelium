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
they get less testing than the Mac build.

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
  The [engines](#engines) use it. You can skip this and add it later.
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
`~/.local/bin` so agents can run them, and the links follow the app when it
updates; on Windows, the app adds its own folders to your PATH, so agents and
the terminals you open next can run them. It needs
no administrator password and writes nothing outside your home folder.

> **A hub on this computer is yours alone.** It runs only while the app is
> running, and only this computer can reach it, so teammates can't join rooms
> on it. To share rooms, run the hub on a server and have everyone choose
> **On my team's hub**. See [Hub & Spoke](#hub-and-spoke).

## What's inside

The app includes everything, at versions tested together:

- the Mycelium hub and its UI;
- a [SLIM](#slim) node for the rooms' messages;
- [herdr](#herdr), where your agents run as terminals you can watch and type
  to;
- the `mycelium` CLI, which agents use to work in rooms;
- the [runner](#machines), which starts your agents and wakes them;
- Pi, which the engines use to call the model;
- the small model behind memory search, so search works offline.

It doesn't include an agent CLI. Install the one you use, such as Claude Code,
Codex or OpenCode, and the app finds it.

## Adding agents

In a room, open **Members**, press **Add** and pick **Your machine**. Start
from a role or write your own instructions, then press **Add to room**. The
agent opens in a herdr terminal and is already a member of the room. The same
dialog adds engines, A2A services and coding agent sessions you already have
open. See [Start Agents From the App](#machines).

To talk to an agent, open the agents terminal: **terminal** in the bar at the
bottom of the window, **Agents terminal** on the home screen or in the app's
menu, or **Open terminal** beside an agent on the **Machines** page.

### Watching an agent's terminal

You can see what an agent on this computer is doing without leaving the room.
Its terminal shows live, read-only, in color:

- **Members:** click the agent, or right-click it and pick **Watch terminal**.
- **Machines:** press **View** on the agent's row.
- **The channel:** press **watch** beside "is working" while it works.
- **Add agent:** when an agent stops at a sign-in or a question as it starts,
  the dialog shows what it's asking.

The view says "Streamed from this machine. Nothing is sent to the hub." The app
reads the terminal from herdr and draws it in its own window. The hub never
receives what a terminal shows, so a key or private code on screen stays on
your computer. For the same reason, an agent running on another computer shows
where it runs instead of its screen. To type to the agent, press **Open its
terminal**.

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

To make the window bigger or smaller, zoom it as you would a browser: ⌘+ and
⌘− (Ctrl+ and Ctrl− on Windows and Linux), and ⌘0 or Ctrl+0 for actual size.
On a Mac these are also in the **View** menu. The app remembers the size you
chose the next time it opens.

![The health check](desktop-health.png)

## Updates

The app checks for a new release shortly after it opens, every few hours while
it runs, and whenever you choose **Check for Updates…**. If one is out, it asks
before installing it. While you haven't installed it yet, the app's header
shows **Update available**, which asks the same question. Once you say yes, a
small window shows the download until the app restarts into the new version.
If your connection drops partway, the window says so and the download carries
on from where it stopped once the connection is back, for up to ten minutes
without progress. If you quit in the middle, the next **Check for Updates…**
picks up the same download. An update installs only if it has the release's
signature, so the app never installs anything the project didn't publish.

herdr keeps running through an update, so your agents aren't interrupted, and
the herdr still running is the one from before it. On a Mac, macOS can then
refuse herdr and its terminals access to folders like Documents, and commands
there fail with "Operation not permitted". When the app sees this, it asks
whether to restart herdr. Restarting stops the agents running in it. If you've
let herdr bring your agents back (`mycelium machine integrations`), each one
reopens in its own conversation; if not, start them again from **Your agents…**.
You can also restart it later with `mycelium desktop restart-herdr`, and the
health check says when it's needed.

### Changing version, and release candidates

**Settings → Version** shows the version you're running and lists releases you
can switch to. Pick one and the app downloads it, checks its signature like any
update, and restarts into it. The hub and the CLI inside the app change with
it. A `mycelium` you installed separately for your terminal (with the install
script or `uv tool`) keeps its own version.

- **Release candidates.** Turn on **Offer release candidates** to list them
  too. A release candidate is the next version, out early to try. While it's
  on, updates also offer the newest release candidate. Turn it off to go back
  to stable releases: you stay on what you have until the next stable release,
  or switch back to one from the list.
- **Going back to an older version.** The app asks twice. Rooms and settings
  saved by a newer version may not open in an older one, and a hub elsewhere
  that runs a newer version may not work with it.

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
