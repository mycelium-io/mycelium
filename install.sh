#!/usr/bin/env bash
# Mycelium CLI installer
# Usage: curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash
#    or: curl -fsSL https://raw.githubusercontent.com/mycelium-io/mycelium/main/install.sh | bash
set -euo pipefail

REPO="mycelium-io/mycelium"
PACKAGE_NAME="mycelium-cli"
BINARY_NAME="mycelium"

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

if ! command -v python3 &>/dev/null; then
  die "python3 is required. Install Python 3.12+ from https://python.org"
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)
if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 12 ]; }; then
  die "Python 3.12+ required (found $PYTHON_VERSION). Install from https://python.org"
fi

if ! command -v curl &>/dev/null; then
  die "curl is required"
fi

ok "Prerequisites OK (Python $PYTHON_VERSION)"

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

# ── Fetch latest release version ─────────────────────────────────────────────
step "Fetching latest release..."

# Follow GitHub's /releases/latest redirect to get the version — no API token needed
LATEST=$(curl -fsSL -o /dev/null -w "%{url_effective}" \
  "https://github.com/${REPO}/releases/latest" 2>/dev/null \
  | grep -oE 'tag/[^/]+' | cut -d/ -f2 || true)

if [ -z "$LATEST" ]; then
  die "Could not determine latest version. Check https://github.com/${REPO}/releases"
fi

WHEEL_VERSION="${LATEST#v}"
INSTALL_FROM="github"

ok "Latest version: $LATEST"

# ── Install ───────────────────────────────────────────────────────────────────
step "Installing mycelium CLI..."

if [ "$INSTALL_FROM" = "github" ]; then
  WHEEL_FILENAME="mycelium_cli-${WHEEL_VERSION}-py3-none-any.whl"
  WHEEL_URL="https://github.com/${REPO}/releases/download/${LATEST}/${WHEEL_FILENAME}"
  WHEEL_TMP="/tmp/${WHEEL_FILENAME}"

  if curl -fsSL "$WHEEL_URL" -o "$WHEEL_TMP" 2>/dev/null; then
    uv tool install "$WHEEL_TMP" --force 2>&1 | sed 's/^/  /'
    rm -f "$WHEEL_TMP"
  else
    warn "Could not download wheel, falling back to PyPI"
    INSTALL_FROM="pypi"
  fi
fi

if [ "$INSTALL_FROM" = "pypi" ]; then
  uv tool install mycelium-cli --force 2>&1 | sed 's/^/  /'
fi

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
echo ""
echo -e "${BOLD}${GREEN}✨ Installation complete!${NC}"
echo ""

# Show PATH instructions if mycelium isn't immediately available
if ! command -v mycelium &>/dev/null; then
  echo -e "${YELLOW}Add mycelium to your PATH:${NC}"
  echo ""
  echo -e "  ${BOLD}export PATH=\"$UV_BIN_DIR:\$PATH\"${NC}"
  echo ""
  echo -e "  To make it permanent, add to your shell config:"
  if [ -f "$HOME/.zshrc" ]; then
    echo -e "  ${DIM}zsh:${NC}  echo 'export PATH=\"$UV_BIN_DIR:\$PATH\"' >> ~/.zshrc && source ~/.zshrc"
  fi
  echo -e "  ${DIM}bash:${NC} echo 'export PATH=\"$UV_BIN_DIR:\$PATH\"' >> ~/.bashrc && source ~/.bashrc"
  echo ""
  echo -e "  Then run:"
fi

echo -e "  ${BOLD}mycelium --help${NC}               — show all commands"
echo -e "  ${BOLD}mycelium install${NC}              — spin up the full stack (Docker)"
echo -e "  ${BOLD}mycelium adapter add openclaw${NC} — wire OpenClaw agents"
echo ""
