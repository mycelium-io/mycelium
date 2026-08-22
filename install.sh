#!/usr/bin/env bash
# Mycelium CLI installer
# Usage: curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash
#    or: curl -fsSL https://raw.githubusercontent.com/mycelium-io/mycelium/main/install.sh | bash
#
# Pin a specific version:
#   MYCELIUM_VERSION=0.1.83 curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash
#   curl -fsSL .../install.sh | bash -s -- --version 0.1.83
set -euo pipefail

REPO="mycelium-io/mycelium"
PACKAGE_NAME="mycelium-cli"
BINARY_NAME="mycelium"
PINNED_VERSION="${MYCELIUM_VERSION:-}"
# Install just the CLI, for a machine that talks to a hub someone else runs —
# a spoke, a CI job, an ephemeral cloud session. There is no local stack to
# bring up, so Docker is not a prerequisite.
CLIENT_ONLY="${MYCELIUM_CLIENT_ONLY:-}"
IMPLIED_CLIENT_ONLY=""

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
    -h|--help)
      cat <<'HELP'
Mycelium CLI installer

Usage:
  install.sh [--version <version>] [--client-only]

Options:
  --version <version>   Install a specific release (e.g. 0.1.83).
                        Defaults to latest. Also settable via MYCELIUM_VERSION env var.
  --client-only         Install only the CLI, for a machine that talks to a hub
                        someone else runs. Skips Docker. Also settable via
                        MYCELIUM_CLIENT_ONLY=1, and implied when MYCELIUM_API_URL
                        names a non-local hub.

Examples:
  curl -fsSL .../install.sh | bash
  curl -fsSL .../install.sh | bash -s -- --version 0.1.83
  curl -fsSL .../install.sh | bash -s -- --client-only
  MYCELIUM_VERSION=0.1.83 curl -fsSL .../install.sh | bash
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

echo ""
echo -e "${BOLD}Mycelium CLI Installer${NC}"
echo ""

# ── Check prerequisites ───────────────────────────────────────────────────────
step "Checking prerequisites..."

# Find a Python 3.12+ binary.  Check versioned binaries first, then fall back
# to the unversioned python3.  This handles Ubuntu/Debian systems where
# python3 points to the system 3.10 but python3.12 is installed via
# deadsnakes or similar (see #86).
PYTHON_CMD=""
PYTHON_VERSION=""
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

if ! command -v curl &>/dev/null; then
  die "curl is required"
fi

# No 3.12+ on the box is not fatal: uv fetches a managed one below.
if [ -n "$PYTHON_CMD" ]; then
  ok "Prerequisites OK (Python $PYTHON_VERSION via $PYTHON_CMD)"
else
  ok "Prerequisites OK (no Python 3.12+ yet — uv will fetch one)"
fi

# ── Check Docker ──────────────────────────────────────────────────────────────
# Only the full stack needs a daemon; a client install talks to a hub over HTTP.
if [ -n "$CLIENT_ONLY" ]; then
  step "Client-only install — skipping Docker..."
  if [ -n "$IMPLIED_CLIENT_ONLY" ]; then
    ok "Client-only install (MYCELIUM_API_URL names a remote hub) — Docker not needed"
  else
    ok "Client-only install — Docker not needed"
  fi
else
  step "Checking Docker..."

  OS=$(uname -s)
  if ! command -v docker &>/dev/null; then
    if [ "$OS" = "Darwin" ]; then
      die "Docker is required. Install Docker Desktop from https://www.docker.com/products/docker-desktop"
    else
      warn "Docker not found — installing..."
      curl -fsSL https://get.docker.com | sh >/dev/null 2>&1
      if ! command -v docker &>/dev/null; then
        die "Docker install failed. Install manually: https://docs.docker.com/engine/install/"
      fi
      ok "Docker installed"
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
UV_PYTHON_FLAG=""
if [ -z "$PYTHON_CMD" ]; then
  step "Fetching a managed Python 3.12 for the CLI..."
  UV_PYTHON_FLAG="--python 3.12"
  ok "Using a uv-managed Python 3.12"
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

# ── Install ───────────────────────────────────────────────────────────────────
step "Installing mycelium CLI..."

WHEEL_FILENAME="mycelium_cli-${WHEEL_VERSION}-py3-none-any.whl"
WHEEL_URL="https://github.com/${REPO}/releases/download/${LATEST}/${WHEEL_FILENAME}"
WHEEL_TMP="/tmp/${WHEEL_FILENAME}"

# The release wheel is the only source. `mycelium-cli` on PyPI is an unrelated
# project, so falling back to it installs someone else's package under our name.
if ! curl -fsSL "$WHEEL_URL" -o "$WHEEL_TMP" 2>/dev/null; then
  die "Could not download $WHEEL_FILENAME from $LATEST. See https://github.com/${REPO}/releases"
fi
# shellcheck disable=SC2086 - UV_PYTHON_FLAG is deliberately word-split (empty = no flag)
uv tool install $UV_PYTHON_FLAG "$WHEEL_TMP" --force 2>&1 | sed 's/^/  /'
rm -f "$WHEEL_TMP"

ok "mycelium CLI installed"

# ── PATH setup ────────────────────────────────────────────────────────────────
UV_BIN_DIR="${UV_TOOL_BIN_DIR:-$HOME/.local/bin}"
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
echo -e "Then:"
if [ -n "$CLIENT_ONLY" ]; then
  echo -e "  ${BOLD}mycelium --help${NC}               — show all commands"
  echo -e "  ${BOLD}mycelium room send \"…\"${NC}         — announce into a room on the hub"
  echo ""
  echo -e "${DIM}  Point it at the hub with MYCELIUM_API_URL, MYCELIUM_ACTIVE_ROOM and${NC}"
  echo -e "${DIM}  MYCELIUM_AGENT_HANDLE:${NC}"
  echo -e "${DIM}  https://mycelium-io.github.io/mycelium/reference.html#ephemeral-agents${NC}"
else
  echo -e "  ${BOLD}mycelium --help${NC}               — show all commands"
  echo -e "  ${BOLD}mycelium install${NC}              — spin up the full stack (Docker)"
  echo -e "  ${BOLD}mycelium agent create <handle>${NC}   — wire a claude_code agent"
fi
echo ""
