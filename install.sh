#!/usr/bin/env bash
# Mycelium CLI installer
# Usage: curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash
#    or: curl -fsSL https://raw.githubusercontent.com/mycelium-io/mycelium/main/install.sh | bash
set -euo pipefail

REPO="mycelium-io/mycelium"
PACKAGE_NAME="mycelium-cli"
BINARY_NAME="mycelium"

# ── Colors ────────────────────────────────────────────────────────────────────
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  CYAN='\033[0;36m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'
  RED='\033[0;31m'; BOLD='\033[1m'; DIM='\033[2m'; NC='\033[0m'
else
  CYAN=''; GREEN=''; YELLOW=''; RED=''; BOLD=''; DIM=''; NC=''
fi

step()    { echo -e "${CYAN}▸${NC} $1"; }
ok()      { echo -e "\033[1A\033[2K${GREEN}✓${NC} $1"; }
warn()    { echo -e "${YELLOW}⚠${NC}  $1"; }
die()     { echo -e "${RED}✗${NC} $1" >&2; exit 1; }

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

LATEST=$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['tag_name'])" 2>/dev/null || true)

if [ -z "$LATEST" ]; then
  # Fallback: check PyPI if GitHub API fails (e.g. rate limit / no releases yet)
  LATEST=$(curl -fsSL "https://pypi.org/pypi/mycelium-cli/json" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['info']['version'])" 2>/dev/null || true)
  INSTALL_FROM="pypi"
else
  # Strip leading 'v' for pip version
  WHEEL_VERSION="${LATEST#v}"
  INSTALL_FROM="github"
fi

if [ -z "$LATEST" ]; then
  die "Could not determine latest version. Check your internet connection."
fi

ok "Latest version: $LATEST"

# ── Install ───────────────────────────────────────────────────────────────────
step "Installing mycelium CLI..."

if [ "$INSTALL_FROM" = "github" ]; then
  # Try to download the wheel from GitHub Releases
  WHEEL_URL="https://github.com/${REPO}/releases/download/${LATEST}/mycelium_cli-${WHEEL_VERSION}-py3-none-any.whl"
  WHEEL_TMP=$(mktemp /tmp/mycelium-XXXXXX.whl)

  if curl -fsSL "$WHEEL_URL" -o "$WHEEL_TMP" 2>/dev/null; then
    uv tool install "$WHEEL_TMP" --force >/dev/null 2>&1
    rm -f "$WHEEL_TMP"
  else
    # Wheel not found in release assets — fall back to PyPI
    INSTALL_FROM="pypi"
  fi
fi

if [ "$INSTALL_FROM" = "pypi" ]; then
  uv tool install mycelium-cli --force >/dev/null 2>&1
fi

ok "mycelium CLI installed"

# ── Verify ────────────────────────────────────────────────────────────────────
step "Verifying installation..."

# uv tool installs to ~/.local/bin (or $UV_TOOL_BIN_DIR)
UV_BIN_DIR="${UV_TOOL_BIN_DIR:-$HOME/.local/bin}"
export PATH="$UV_BIN_DIR:$PATH"

if ! command -v mycelium &>/dev/null; then
  warn "mycelium not found in PATH — you may need to add $UV_BIN_DIR to your PATH"
  echo ""
  echo -e "  Add to your shell config:"
  echo -e "  ${BOLD}export PATH=\"$UV_BIN_DIR:\$PATH\"${NC}"
  echo ""
else
  CLI_VERSION=$(mycelium --version 2>/dev/null | head -1 || echo "unknown")
  ok "mycelium CLI ready ($CLI_VERSION)"
fi

# ── PATH reminder ─────────────────────────────────────────────────────────────
if [[ ":$PATH:" != *":$UV_BIN_DIR:"* ]]; then
  echo ""
  echo -e "${YELLOW}Add to PATH${NC} (pick your shell):"
  echo ""
  if [ -f "$HOME/.zshrc" ]; then
    echo -e "  ${DIM}zsh:${NC}  echo 'export PATH=\"$UV_BIN_DIR:\$PATH\"' >> ~/.zshrc && source ~/.zshrc"
  fi
  if [ -f "$HOME/.bashrc" ] || [ -f "$HOME/.bash_profile" ]; then
    echo -e "  ${DIM}bash:${NC} echo 'export PATH=\"$UV_BIN_DIR:\$PATH\"' >> ~/.bashrc && source ~/.bashrc"
  fi
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}✨ Installation complete!${NC}"
echo ""
echo -e "  ${BOLD}mycelium --help${NC}               — show all commands"
echo -e "  ${BOLD}mycelium install${NC}              — spin up the full stack (Docker)"
echo -e "  ${BOLD}mycelium adapter add openclaw${NC} — wire OpenClaw agents"
echo ""
