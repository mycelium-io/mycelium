#!/usr/bin/env bash
# Mycelium installer
# Usage: curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash
#    or: curl -fsSL https://raw.githubusercontent.com/mycelium-io/mycelium/main/install.sh | bash
#
# On an Apple silicon Mac this installs Mycelium for Mac, which runs the hub,
# the UI, the SLIM node and the runner itself (no Docker), and puts its
# `mycelium` CLI on PATH. Anywhere else it installs the CLI for the Docker stack
# (`mycelium install`). --docker picks the Docker stack on a Mac too, and
# --client-only installs just the CLI, for a machine that uses someone else's hub.
#
# Pin a specific version:
#   MYCELIUM_VERSION=0.1.83 curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash
#   curl -fsSL .../install.sh | bash -s -- --version 0.1.83
set -euo pipefail

REPO="mycelium-io/mycelium"
PINNED_VERSION="${MYCELIUM_VERSION:-}"
# Install just the CLI, for a machine that talks to a hub someone else runs —
# a spoke, a CI job, an ephemeral cloud session. There is no local stack to
# bring up, so neither the app nor Docker is needed.
CLIENT_ONLY="${MYCELIUM_CLIENT_ONLY:-}"
IMPLIED_CLIENT_ONLY=""
# Run the hub as the Docker compose stack rather than the Mac app.
DOCKER="${MYCELIUM_DOCKER:-}"
# Install the app without opening it.
NO_OPEN="${MYCELIUM_NO_OPEN:-}"

APP_ASSET="Mycelium-macos-arm64.app.tar.gz"
APP_NAME="Mycelium.app"
# Where the app's hub and UI listen (mycelium/desktop/supervisor.py).
APP_HUB_URL="http://127.0.0.1:8000"
APP_UI_URL="http://127.0.0.1:3717"

# Parse CLI args (curl | bash -s -- --version X)
while [ $# -gt 0 ]; do
  case "$1" in
    --version)
      PINNED_VERSION="${2:-}"
      shift 2
      ;;
    --version=*)
      PINNED_VERSION="${1#--version=}"
      shift
      ;;
    --client-only)
      CLIENT_ONLY=1
      shift
      ;;
    --docker)
      DOCKER=1
      shift
      ;;
    --no-open)
      NO_OPEN=1
      shift
      ;;
    -h|--help)
      cat <<'HELP'
Mycelium installer

Usage:
  install.sh [--version <version>] [--docker | --client-only] [--no-open]

On an Apple silicon Mac, installs Mycelium for Mac into /Applications (or
~/Applications), links its `mycelium` CLI into ~/.local/bin and opens it. The
app runs the hub, the UI, the SLIM node and the runner itself: no Docker.
Anywhere else, installs the CLI; `mycelium install` then brings up the Docker stack.

Options:
  --version <version>   Install a specific release (e.g. 0.1.83).
                        Defaults to latest. Also settable via MYCELIUM_VERSION env var.
  --docker              Install the CLI for the Docker stack instead of the Mac
                        app (the default off a Mac). Also settable via
                        MYCELIUM_DOCKER=1.
  --client-only         Install only the CLI, for a machine that talks to a hub
                        someone else runs. Needs neither the app nor Docker. Also
                        settable via MYCELIUM_CLIENT_ONLY=1, and implied when
                        MYCELIUM_API_URL names a non-local hub.
  --no-open             Install the Mac app without opening it. Also settable via
                        MYCELIUM_NO_OPEN=1.

Every download is verified against the release's checksums.txt before anything
is installed. Set MYCELIUM_SKIP_CHECKSUM=1 to skip that, for a release that
predates checksums.txt.

Examples:
  curl -fsSL .../install.sh | bash
  curl -fsSL .../install.sh | bash -s -- --docker
  curl -fsSL .../install.sh | bash -s -- --client-only
  curl -fsSL .../install.sh | bash -s -- --version 0.1.83
HELP
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      echo "Run with --help for usage." >&2
      exit 1
      ;;
  esac
done

# Normalize: strip a leading v if the user passed --version v0.1.83
if [ -n "$PINNED_VERSION" ]; then
  PINNED_VERSION="${PINNED_VERSION#v}"
fi

# Naming a hub that isn't on this machine says what this machine is: a client of
# someone else's stack.
if [ -z "$CLIENT_ONLY" ] && [ -n "${MYCELIUM_API_URL:-}" ]; then
  case "$MYCELIUM_API_URL" in
    *localhost*|*127.0.0.1*|*0.0.0.0*) ;;
    *) CLIENT_ONLY=1; IMPLIED_CLIENT_ONLY=1 ;;
  esac
fi

if [ -n "$CLIENT_ONLY" ] && [ -n "$DOCKER" ]; then
  echo "--client-only and --docker can't be used together: a client runs no stack." >&2
  exit 1
fi

# ── Colors ────────────────────────────────────────────────────────────────────
# Note: curl | bash pipes through a non-TTY stdin but stdout may still be a TTY.
# Use /dev/tty check for escape codes that require a real terminal.
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  CYAN='\033[0;36m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'
  RED='\033[0;31m'; BOLD='\033[1m'; DIM='\033[2m'; NC='\033[0m'
  IS_TTY=true
else
  CYAN=''; GREEN=''; YELLOW=''; RED=''; BOLD=''; DIM=''; NC=''
  IS_TTY=false
fi

step() { echo -e "${CYAN}▸${NC} $1"; }
ok()   {
  if [ "$IS_TTY" = true ]; then
    echo -e "\033[1A\033[2K${GREEN}✓${NC} $1"
  else
    echo -e "${GREEN}✓${NC} $1"
  fi
}
warn() { echo -e "${YELLOW}⚠${NC}  $1"; }
die()  { echo -e "${RED}✗${NC} $1" >&2; exit 1; }

# ── What to install ───────────────────────────────────────────────────────────
# app:    Mycelium for Mac (Apple silicon), which carries its own CLI.
# docker: the CLI, for the Docker stack `mycelium install` brings up.
# client: the CLI alone, for someone else's hub.
OS=$(uname -s)
apple_silicon() {
  # uname -m says x86_64 under Rosetta, so ask the hardware.
  [ "$OS" = "Darwin" ] && [ "$(sysctl -n hw.optional.arm64 2>/dev/null || echo 0)" = "1" ]
}

if [ -n "$CLIENT_ONLY" ]; then
  MODE=client
elif [ -n "$DOCKER" ]; then
  MODE=docker
elif apple_silicon; then
  MODE=app
else
  MODE=docker
fi

echo ""
echo -e "${BOLD}Mycelium Installer${NC}"
echo ""

if [ "$MODE" = docker ] && [ -z "$DOCKER" ] && [ "$OS" = "Darwin" ]; then
  warn "Mycelium for Mac is built for Apple silicon only, so this Intel Mac gets the Docker stack."
fi

# ── Check prerequisites ───────────────────────────────────────────────────────
step "Checking prerequisites..."

if ! command -v curl &>/dev/null; then
  die "curl is required"
fi

PYTHON_CMD=""
PYTHON_VERSION=""
if [ "$MODE" = app ]; then
  # The app carries its own CLI, so there is no Python to find.
  command -v tar &>/dev/null || die "tar is required"
  ok "Prerequisites OK (macOS $(sw_vers -productVersion 2>/dev/null || echo '?'), Apple silicon)"
else
  # Find a Python 3.12+ binary.  Check versioned binaries first, then fall back
  # to the unversioned python3.  This handles Ubuntu/Debian systems where
  # python3 points to the system 3.10 but python3.12 is installed via
  # deadsnakes or similar (see #86).
  for candidate in python3.13 python3.12 python3; do
    if command -v "$candidate" &>/dev/null; then
      ver=$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
      major=$(echo "$ver" | cut -d. -f1)
      minor=$(echo "$ver" | cut -d. -f2)
      if [ "$major" -ge 3 ] && [ "$minor" -ge 12 ]; then
        PYTHON_CMD="$candidate"
        PYTHON_VERSION="$ver"
        break
      fi
    fi
  done

  # No 3.12+ on the box is not fatal: uv fetches a managed one below.
  if [ -n "$PYTHON_CMD" ]; then
    ok "Prerequisites OK (Python $PYTHON_VERSION via $PYTHON_CMD)"
  else
    ok "Prerequisites OK (no Python 3.12+ yet — uv will fetch one)"
  fi
fi

# ── Check Docker ──────────────────────────────────────────────────────────────
# Only the Docker stack needs a daemon: the Mac app runs its own hub, and a
# client install talks to a hub over HTTP.
if [ "$MODE" = client ]; then
  step "Client-only install — skipping Docker..."
  if [ -n "$IMPLIED_CLIENT_ONLY" ]; then
    ok "Client-only install (MYCELIUM_API_URL names a remote hub) — Docker not needed"
  else
    ok "Client-only install — Docker not needed"
  fi
elif [ "$MODE" = docker ]; then
  step "Checking Docker..."

  if ! command -v docker &>/dev/null; then
    # Installing Docker runs a downloaded script as root, so leave that to the user.
    if [ "$OS" = "Darwin" ]; then
      die "Docker is required for --docker. Install Docker Desktop from https://www.docker.com/products/docker-desktop, then run this installer again."
    else
      die "Docker is required. Install it from https://docs.docker.com/engine/install/, then run this installer again (or pass --client-only to skip Docker)."
    fi
  elif ! docker info >/dev/null 2>&1; then
    if [ "$OS" = "Darwin" ]; then
      die "Docker Desktop is installed but not running. Start Docker Desktop and try again."
    else
      warn "Docker daemon not running — attempting to start..."
      sudo systemctl start docker >/dev/null 2>&1 || true
      if ! docker info >/dev/null 2>&1; then
        die "Docker daemon could not be started. Run: sudo systemctl start docker"
      fi
      ok "Docker daemon started"
    fi
  else
    DOCKER_VERSION=$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo "unknown")
    ok "Docker found ($DOCKER_VERSION)"
  fi
fi

# ── Install uv if not present ─────────────────────────────────────────────────
UV_PYTHON_FLAG=""
if [ "$MODE" != app ]; then
  if ! command -v uv &>/dev/null; then
    step "Installing uv (Python package manager)..."
    curl -fsSL https://astral.sh/uv/install.sh | sh >/dev/null 2>&1
    # Add uv to PATH for this session
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    if ! command -v uv &>/dev/null; then
      die "Failed to install uv. Install manually: https://docs.astral.sh/uv/getting-started/installation/"
    fi
    ok "uv installed"
  else
    ok "uv found ($(uv --version 2>/dev/null | head -1))"
  fi

  # The CLI needs 3.12+. With none on the box, let uv fetch a managed one rather
  # than failing — an ephemeral container usually ships an older system Python and
  # has no way to add one.
  if [ -z "$PYTHON_CMD" ]; then
    step "Fetching a managed Python 3.12 for the CLI..."
    UV_PYTHON_FLAG="--python 3.12"
    ok "Using a uv-managed Python 3.12"
  fi
fi

# ── Resolve release version ──────────────────────────────────────────────────
if [ -n "$PINNED_VERSION" ]; then
  step "Using pinned version v$PINNED_VERSION..."
  LATEST="v$PINNED_VERSION"
  WHEEL_VERSION="$PINNED_VERSION"
  ok "Pinned version: $LATEST"
else
  step "Fetching latest release..."

  # Follow GitHub's /releases/latest redirect to get the version — no API token needed
  LATEST=$(curl -fsSL -o /dev/null -w "%{url_effective}" \
    "https://github.com/${REPO}/releases/latest" 2>/dev/null \
    | grep -oE 'tag/[^/]+' | cut -d/ -f2 || true)

  if [ -z "$LATEST" ]; then
    die "Could not determine latest version. Check https://github.com/${REPO}/releases"
  fi

  WHEEL_VERSION="${LATEST#v}"
  ok "Latest version: $LATEST"
fi

RELEASE_URL="https://github.com/${REPO}/releases/download/${LATEST}"

# A private directory, not a fixed /tmp path another user could pre-plant.
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

sha256_of() {
  if command -v sha256sum &>/dev/null; then
    sha256sum "$1" | cut -d' ' -f1
  elif command -v shasum &>/dev/null; then
    shasum -a 256 "$1" | cut -d' ' -f1
  else
    die "sha256sum or shasum is required to verify the download"
  fi
}

# Check a download against the release's checksums.txt, or stop before anything
# is installed. checksums.txt names the release binaries as binaries/<file>, so
# an entry matches on its file name. MYCELIUM_SKIP_CHECKSUM=1 is for releases
# that predate checksums.txt.
verify() {
  local file="$1" name
  name="$(basename "$1")"
  if [ -n "${MYCELIUM_SKIP_CHECKSUM:-}" ]; then
    warn "Skipping checksum verification (MYCELIUM_SKIP_CHECKSUM is set)"
    return
  fi
  step "Verifying checksum..."
  if [ ! -f "$WORK_DIR/checksums.txt" ] \
    && ! curl -fsSL "$RELEASE_URL/checksums.txt" -o "$WORK_DIR/checksums.txt" 2>/dev/null; then
    die "Could not download checksums.txt from $LATEST, so $name can't be verified. Set MYCELIUM_SKIP_CHECKSUM=1 to install anyway."
  fi
  local expected actual
  expected=$(awk -v f="$name" '{ p = $2; sub(/^\*/, "", p) } p == f || substr(p, length(p) - length(f)) == "/" f { print $1; exit }' "$WORK_DIR/checksums.txt")
  if [ -z "$expected" ]; then
    die "checksums.txt for $LATEST has no entry for $name. Set MYCELIUM_SKIP_CHECKSUM=1 to install anyway."
  fi
  actual=$(sha256_of "$file")
  if [ "$actual" != "$expected" ]; then
    die "Checksum mismatch for $name (expected $expected, got $actual). Nothing was installed."
  fi
  ok "Checksum verified"
}

UV_BIN_DIR="${UV_TOOL_BIN_DIR:-$HOME/.local/bin}"

if [ "$MODE" = app ]; then
  # ── Install Mycelium for Mac ────────────────────────────────────────────────
  step "Downloading Mycelium for Mac ($LATEST, a few hundred MB)..."
  ARCHIVE="$WORK_DIR/$APP_ASSET"
  if ! curl -fSL --progress-bar "$RELEASE_URL/$APP_ASSET" -o "$ARCHIVE"; then
    die "Could not download $APP_ASSET from $LATEST. See https://github.com/${REPO}/releases (or pass --docker for the Docker stack)."
  fi
  ok "Downloaded $APP_ASSET"

  verify "$ARCHIVE"

  step "Unpacking..."
  mkdir -p "$WORK_DIR/app"
  tar -xzf "$ARCHIVE" -C "$WORK_DIR/app"
  [ -d "$WORK_DIR/app/$APP_NAME" ] || die "$APP_ASSET has no $APP_NAME in it. Nothing was installed."
  ok "Unpacked $APP_NAME"

  # /Applications is writable by an admin without sudo; anyone else gets their own.
  if [ -n "${MYCELIUM_APP_DIR:-}" ]; then
    APP_DIR="$MYCELIUM_APP_DIR"
  elif [ -w /Applications ]; then
    APP_DIR="/Applications"
  else
    APP_DIR="$HOME/Applications"
  fi
  mkdir -p "$APP_DIR"
  APP_PATH="$APP_DIR/$APP_NAME"

  # Replacing a running app would pull it out from under itself. Quitting it
  # leaves agents running: they live in herdr, not in the app.
  # Only the app's own executable counts: herdr, started from the same bundle,
  # outlives the app on purpose.
  WAS_RUNNING=""
  APP_EXE="$(defaults read "$APP_PATH/Contents/Info" CFBundleExecutable 2>/dev/null || echo mycelium-desktop)"
  app_running() { pgrep -f "$APP_PATH/Contents/MacOS/$APP_EXE" >/dev/null 2>&1; }
  if app_running; then
    WAS_RUNNING=1
    step "Quitting the running Mycelium to replace it (agents keep running in herdr)..."
    osascript -e 'tell application id "io.mycelium.desktop" to quit' >/dev/null 2>&1 || true
    for _ in $(seq 1 30); do
      app_running || break
      sleep 1
    done
    if app_running; then
      die "Mycelium is still running. Quit it from its menu bar icon and run this installer again."
    fi
    ok "Quit Mycelium"
  fi

  step "Installing $APP_NAME into $APP_DIR..."
  # Move the old copy aside rather than deleting it first, so a failed move
  # leaves the app that was there.
  if [ -e "$APP_PATH" ]; then
    mv "$APP_PATH" "$WORK_DIR/previous.app" \
      || die "Could not replace $APP_PATH. Remove it and run this installer again."
  fi
  if ! mv "$WORK_DIR/app/$APP_NAME" "$APP_PATH"; then
    [ -e "$WORK_DIR/previous.app" ] && mv "$WORK_DIR/previous.app" "$APP_PATH"
    die "Could not install into $APP_DIR."
  fi
  ok "Mycelium for Mac installed ($APP_PATH)"

  # The app links its own CLI into ~/.local/bin when it starts; doing it here as
  # well means `mycelium` works in this terminal straight away. Same rule as the
  # app: only a link is replaced, and a real file there is the user's own.
  step "Linking the mycelium CLI..."
  mkdir -p "$UV_BIN_DIR"
  for name in mycelium herdr; do
    source_bin="$APP_PATH/Contents/MacOS/$name"
    target="$UV_BIN_DIR/$name"
    [ -f "$source_bin" ] || continue
    if [ -e "$target" ] && [ ! -L "$target" ]; then
      warn "$target is not a link, so it was left alone. The app's copy is $source_bin."
      continue
    fi
    ln -sf "$source_bin" "$target"
  done
  ok "mycelium CLI linked into $UV_BIN_DIR"
else
  # ── Install the CLI ─────────────────────────────────────────────────────────
  step "Installing mycelium CLI..."

  WHEEL_FILENAME="mycelium_cli-${WHEEL_VERSION}-py3-none-any.whl"
  WHEEL_TMP="$WORK_DIR/$WHEEL_FILENAME"

  # The release wheel is the only source. `mycelium-cli` on PyPI is an unrelated
  # project, so falling back to it installs someone else's package under our name.
  if ! curl -fsSL "$RELEASE_URL/$WHEEL_FILENAME" -o "$WHEEL_TMP" 2>/dev/null; then
    die "Could not download $WHEEL_FILENAME from $LATEST. See https://github.com/${REPO}/releases"
  fi

  verify "$WHEEL_TMP"

  # shellcheck disable=SC2086 - UV_PYTHON_FLAG is deliberately word-split (empty = no flag)
  uv tool install $UV_PYTHON_FLAG "$WHEEL_TMP" --force 2>&1 | sed 's/^/  /'

  ok "mycelium CLI installed"
fi

# ── PATH setup ────────────────────────────────────────────────────────────────
export PATH="$UV_BIN_DIR:$PATH"

# Auto-write to shell rc files so it persists
PATH_LINE="export PATH=\"$UV_BIN_DIR:\$PATH\""
for rcfile in "$HOME/.bashrc" "$HOME/.zshrc"; do
  if [ -f "$rcfile" ] && ! grep -qF "$UV_BIN_DIR" "$rcfile" 2>/dev/null; then
    echo "" >> "$rcfile"
    echo "# mycelium" >> "$rcfile"
    echo "$PATH_LINE" >> "$rcfile"
  fi
done

# ── Verify ────────────────────────────────────────────────────────────────────
step "Verifying installation..."

if ! command -v mycelium &>/dev/null; then
  warn "mycelium not found in PATH after install"
  echo -e "  Run: ${BOLD}export PATH=\"$UV_BIN_DIR:\$PATH\"${NC}"
else
  CLI_VERSION=$(mycelium --version 2>/dev/null | head -1 || echo "unknown")
  ok "mycelium CLI ready ($CLI_VERSION)"
fi

# ── Open the app ──────────────────────────────────────────────────────────────
HUB_UP=""
FIRST_RUN=""
if [ "$MODE" = app ]; then
  # The app saves its first-run choice (a hub here, or someone else's) here.
  SETTINGS="${MYCELIUM_DESKTOP_SETTINGS:-$HOME/.mycelium/desktop.json}"
  [ -f "$SETTINGS" ] || FIRST_RUN=1

  if [ -z "$NO_OPEN" ] || [ -n "$WAS_RUNNING" ]; then
    step "Opening Mycelium..."
    if open "$APP_PATH" 2>/dev/null; then
      ok "Mycelium opened"
      # With a hub already chosen, the app starts it on its own: wait for it.
      if [ -z "$FIRST_RUN" ] && grep -q '"mode": *"hub"' "$SETTINGS" 2>/dev/null; then
        step "Waiting for the hub at $APP_HUB_URL..."
        for _ in $(seq 1 90); do
          if curl -fsS -o /dev/null "$APP_HUB_URL/health" 2>/dev/null; then
            HUB_UP=1
            break
          fi
          sleep 1
        done
        if [ -n "$HUB_UP" ]; then
          ok "Hub running at $APP_HUB_URL"
        else
          warn "The hub hasn't answered yet. The app's health screen says why; its log is ~/.mycelium/logs/desktop.log."
        fi
      fi
    else
      warn "Couldn't open Mycelium from this terminal. Open it from $APP_DIR."
    fi
  fi
fi

# ── Done ──────────────────────────────────────────────────────────────────────

# Detect rc file based on current shell
case "$(basename "${SHELL:-bash}")" in
  zsh)  RC_FILE="~/.zshrc" ;;
  fish) RC_FILE="~/.config/fish/config.fish" ;;
  *)    RC_FILE="~/.bashrc" ;;
esac

echo ""
echo -e "${BOLD}${GREEN}✨ Installation complete!${NC}"
echo ""
echo -e "Run this to activate ${DIM}(and make it permanent):${NC}"
echo ""
echo -e "  ${BOLD}echo 'export PATH=\"$UV_BIN_DIR:\$PATH\"' >> $RC_FILE && source $RC_FILE${NC}"
echo ""
if [ "$MODE" = app ]; then
  if [ -n "$FIRST_RUN" ]; then
    echo -e "Next, in the Mycelium window: choose where rooms live (${BOLD}On this Mac${NC}, or your"
    echo -e "team's hub), pick the folder agents may start in, and ${BOLD}Start Mycelium${NC}. A hub on"
    echo -e "this Mac answers at ${BOLD}$APP_HUB_URL${NC}; the app is at ${BOLD}$APP_UI_URL${NC}."
    if [ -n "$NO_OPEN" ]; then
      echo -e "${DIM}  Open it with: open \"$APP_PATH\"${NC}"
    fi
    echo ""
  fi
  echo -e "Then:"
  echo -e "  ${BOLD}mycelium --help${NC}                — show all commands"
  echo -e "  ${BOLD}mycelium doctor --mode desktop${NC} — check what the app runs"
  echo -e "  ${BOLD}mycelium room create <name>${NC}    — make a room for your agents"
  echo ""
  echo -e "${DIM}  Mycelium updates itself (Check for Updates… in its menu bar icon).${NC}"
  echo -e "${DIM}  Prefer the Docker stack? Run this installer again with --docker:${NC}"
  echo -e "${DIM}  curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash -s -- --docker${NC}"
elif [ "$MODE" = client ]; then
  echo -e "Then:"
  echo -e "  ${BOLD}mycelium --help${NC}               — show all commands"
  echo -e "  ${BOLD}mycelium room send \"…\"${NC}         — announce into a room on the hub"
  echo ""
  echo -e "${DIM}  Point it at the hub with MYCELIUM_API_URL, MYCELIUM_ACTIVE_ROOM and${NC}"
  echo -e "${DIM}  MYCELIUM_AGENT_HANDLE:${NC}"
  echo -e "${DIM}  https://mycelium-io.github.io/mycelium/guides.html#ephemeral-agents${NC}"
else
  echo -e "Then:"
  echo -e "  ${BOLD}mycelium --help${NC}               — show all commands"
  echo -e "  ${BOLD}mycelium install${NC}              — spin up the full stack (Docker)"
  echo -e "  ${BOLD}mycelium agent create <handle>${NC}   — wire a claude_code agent"
fi
echo ""
