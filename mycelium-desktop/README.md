# Mycelium for macOS

The desktop app. A thin [Tauri 2](https://v2.tauri.app) shell over
`mycelium desktop serve`, which runs everything a Mac needs: the SLIM node,
the hub, the room UI and the runner in hub mode, or only the runner when the
Mac joins someone else's hub.

The shell adds:

- **first run**: run a hub here, or connect to one; the agent CLIs found on
  this Mac; the folder agents may start in. Saved to `~/.mycelium/desktop.json`.
- **the main window**: a loading screen while the supervisor starts, then the
  room UI itself. Its user agent ends in `MyceliumDesktop/<version>`, which is
  how the UI knows it can offer app-only links.
- **the tray**: what is running, the agents terminal, start at login, switch
  hub, quit.
- **`mycelium://` links**: `mycelium://join?hub=<url>&room=<name>` switches
  this Mac to that hub (after asking) and opens the room;
  `mycelium://terminal?pane=<herdr pane>` opens the agents terminal on it.
- **the agents terminal**: herdr, attached in a window. The only program the
  terminal commands can start is herdr.
- **PATH**: the bundled `mycelium` and `herdr` are linked into `~/.local/bin`,
  because agents in herdr run `mycelium` commands from their own shells. An
  existing file there that isn't a link is left alone.

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

The app carries everything it runs, so it works on a Mac with nothing else
installed. `scripts/stage-sidecars.sh` stages it all, pinned:

- programs, into `src-tauri/binaries/` with the target triple Tauri expects:
  `mycelium` (PyInstaller), `herdr`, `slimctl` (2.1.x, to match the hub's
  `slim-bindings`) and `node`;
- directories, into `src-tauri/resources/`: `hub/` (the hub, PyInstaller),
  `ui/` (the UI's standalone build), `models/` (the search model) and `pi/`
  (Pi, which engines think with).

```bash
npm run sidecars                  # all of it, several minutes
bash scripts/stage-sidecars.sh ui # or just the steps you changed
npx tauri build --bundles app,dmg --config src-tauri/tauri.bundle.conf.json
```

The disk image lands in `src-tauri/target/release/bundle/dmg/`. Building it
arranges the Finder window with AppleScript, so the first local build asks
whether your terminal may control Finder; say yes, or the last step fails.
The release workflow builds the same thing and attaches it to each release
as `Mycelium-macos-arm64.dmg`.

`MYCELIUM_BIN=/path/to/mycelium` stages a `mycelium` binary you already have
instead of building one. `npx tauri build --bundles app` without the bundle
config builds the shell alone, which is enough to check it compiles.

What goes wrong at run time is in `~/.mycelium/logs/desktop.log`, which the
app opens from **Show log** on its loading and health screens.

## Signing

Not configured yet. A build runs on the machine that made it, but macOS will
refuse a downloaded copy until the app and every bundled program are signed
with an Apple Developer ID and notarized. That needs the team's Developer ID
certificate and a notarization login in CI.
