#!/usr/bin/env bash
# Generates docs/banner.png
# Requires: ImageMagick 7+, Python 3 with `pip install playwright` +
# `playwright install chromium`, IBM Plex Sans
# (brew install --cask font-ibm-plex-sans), Cormorant Garamond
# (brew install --cask font-cormorant-garamond)
set -euo pipefail

DIR="$(dirname "$0")"
LOGO="$DIR/../docs/logo.png"
OUT="$DIR/../docs/banner.png"
NETWORK="$(mktemp -t mycelium-banner-network).png"
PLEX="$HOME/Library/Fonts/IBMPlexSans-Regular.otf"
CORMORANT="$HOME/Library/Fonts/CormorantGaramond-SemiBoldItalic.ttf"

trap 'rm -f "$NETWORK"' EXIT

# Renders at 2x (2400x600) so the linework stays smooth after the final
# downscale to 1200x300 — supersampling instead of drawing at native size.
python3 "$DIR/gen-banner-network.py" "$NETWORK" 2400 600

magick "$NETWORK" \
  \( "$LOGO" -resize 260x260 \
     \( +clone -background black -shadow 60x24+0+12 \) \
     +swap -background none -layers merge \) \
  -gravity North -geometry +0+30 -composite \
  -font "$CORMORANT" \
  -pointsize 160 \
  -fill '#ffffff' \
  -gravity North \
  -annotate +0+304 'mycelium' \
  -font "$PLEX" \
  -pointsize 44 \
  -fill '#8fd6de' \
  -gravity North \
  -annotate +0+490 'coordination layer for multi-agent systems' \
  -resize 1200x300 \
  "$OUT"

echo "Banner written to $OUT"
