# Mycelium for Mac, Linux and Windows

The desktop app. A thin [Tauri 2](https://v2.tauri.app) shell over
`mycelium desktop serve`, which runs everything a machine needs: the SLIM node,
the hub, the room UI and the runner in hub mode, or only the runner when the
machine joins someone else's hub. One codebase, three packages:

| Platform | Package | Updates |
| --- | --- | --- |
| macOS (Apple silicon) | `Mycelium-macos-arm64.dmg`, signed and notarized | in place, from the app |
| Linux (x86-64) | `Mycelium-linux-x86_64.AppImage`, one file, no install | in place, from the app |
| Windows (x64) | `Mycelium-windows-x86_64-setup.exe`, a per-user installer | in place, from the app |

Linux and Windows are a preview: built by every release, but a failed build
there doesn't hold a release back (`.github/workflows/desktop.yml`).

The shell adds:

- **first run**: run a hub here, or connect to one; the agent CLIs found on
  this machine; the folder agents may start in. Saved to `~/.mycelium/desktop.json`.
- **the main window**: a loading screen while the supervisor starts, then the
  room UI itself. Its user agent ends in `MyceliumDesktop/<version>`, which is
  how the UI knows it can offer app-only links.
- **the tray**: what is running, the agents terminal, start at login, switch
  hub, quit.
- **`mycelium://` links**: `mycelium://join?hub=<url>&room=<name>` switches
  this machine to that hub (after asking) and opens the room;
  `mycelium://terminal?pane=<herdr pane>` opens the agents terminal on it.
- **the agents terminal**: herdr, attached in a window. The only program the
  terminal commands can start is herdr.
- **PATH**: the bundled `mycelium` and `herdr` are linked into `~/.local/bin`
  (macOS, Linux), because agents in herdr run `mycelium` commands from their
  own shells. An existing file there that isn't a link is left alone. On
  Windows nothing is linked: the app's folder goes first on the PATH of
  everything it starts.

The hub's UI, once loaded, gets no IPC: the capability lists only the app's
own pages, and every command also checks the calling page's origin.

## Run it in development

```bash
cd mycelium-desktop
npm install
npx tauri dev
```

Nothing needs to be bundled for this: the app uses the `mycelium` and `herdr`
already installed (on PATH or in `~/.local/bin`). Useful overrides:

| Variable | Effect |
| --- | --- |
| `MYCELIUM_DESKTOP_SETTINGS` | Use this settings file instead of `~/.mycelium/desktop.json`. |
| `MYCELIUM_DESKTOP_SUPERVISOR` | Run this program instead of `mycelium` for `desktop serve`. `scripts/fake-supervisor.mjs` brings each component up in turn and reports the UI at `$FAKE_UI_URL` (default `http://localhost:3100`). |

## Build the app

The app carries everything it runs, so it works with nothing else installed.
`scripts/stage-sidecars.sh` stages it all, pinned, for the platform it runs on
(on Windows, in Git Bash):

- programs, into `src-tauri/binaries/` with the target triple Tauri expects:
  `mycelium` (PyInstaller), `herdr`, `slimctl` (2.1.x, to match the hub's
  `slim-bindings`) and `node`;
- directories, into `src-tauri/resources/`: `hub/` (the hub, PyInstaller),
  `ui/` (the UI's standalone build), `models/` (the search model), `pi/`
  (Pi, which engines think with) and, on Windows, `conpty/` (the console
  host herdr runs its panes in).

Where they end up differs by platform, and the supervisor
(`mycelium/desktop/supervisor.py`, `Locator`) looks in all three: programs
beside the app's executable (`Contents/MacOS`, the AppImage's `usr/bin`, the
install folder), resources in `Contents/Resources`, `usr/lib/Mycelium`, or
the install folder itself.

```bash
npm run sidecars                  # all of it, several minutes
bash scripts/stage-sidecars.sh ui # or just the steps you changed

# macOS
npx tauri build --bundles app --config src-tauri/tauri.bundle.conf.json
bash scripts/package-mac.sh       # sign it, then make the disk image
# Linux (needs Tauri's prerequisites: webkit2gtk 4.1 and friends)
bash scripts/package-linux.sh     # the AppImage
# Windows (Git Bash)
bash scripts/package-windows.sh   # the installer
```

Each packaging script, given `TAURI_SIGNING_PRIVATE_KEY`, also signs what the
updater installs and writes `updater-<platform>.json`; the release merges
those into the one `latest.json` every copy of the app checks
(`scripts/updater.sh`). To try a Linux or Windows build without releasing,
run the **Desktop app** workflow by hand from the Actions tab.

`package-mac.sh` signs every program inside the app and then the app, and
makes `src-tauri/target/release/bundle/dmg/Mycelium-macos-arm64.dmg` with
`dmgbuild` (layout in `scripts/dmg-settings.py`). Both matter for a
downloaded copy: an app whose bundled programs were added after it was
signed is "damaged" to macOS, and Tauri's own disk image lays out its window
by scripting Finder, which fails on CI. The signature is ad-hoc until
`SIGN_IDENTITY` names a Developer ID. The release workflow runs the same
steps and attaches the image to each release.

`MYCELIUM_BIN=/path/to/mycelium` stages a `mycelium` binary you already have
instead of building one. `npx tauri build --bundles app` without the bundle
config builds the shell alone, which is enough to check it compiles.

What goes wrong at run time is in `~/.mycelium/logs/desktop.log`, which the
app opens from **Show log** on its loading and health screens.

## Signing

On a Mac, every program and the app are signed with the project's Developer
ID and notarized in CI (`APPLE_*` secrets); without them a build is signed
ad hoc. The Windows installer isn't Authenticode-signed yet, so SmartScreen
asks before its first run; signing it needs a code-signing certificate and
Tauri's `bundle.windows.signCommand`. An AppImage needs no signature to run.

## Platform notes

- **Linux**: built on Ubuntu 22.04, so it runs where glibc is 2.35 or newer.
  It registers `mycelium://` links itself on first start, and turns off
  WebKitGTK's DMA-BUF renderer (a blank window on some GPUs) unless
  `WEBKIT_DISABLE_DMABUF_RENDERER` is already set. The `~/.local/bin` links
  point into the running AppImage, so they work while the app is open, like
  the agents they serve.
- **Windows**: installs to `%LOCALAPPDATA%\Mycelium` with no administrator
  prompt. herdr's Windows build is in beta upstream. Programs the app starts
  open no console window.
