#!/usr/bin/env bash
# Generates OG images (1200x630) for docs and landing page
# Requires: ImageMagick 7+, Inter font, Didot font
#
# Outputs:
#   docs/og.png
#   ../../mycelium-io.github.io/og.png  (if that repo is checked out alongside)

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOGO="$SCRIPT_DIR/../docs/logo.png"
INTER="$HOME/Library/Fonts/InterVariable.ttf"
CORMORANT="$HOME/Library/Fonts/CormorantGaramond-SemiBoldItalic.ttf"

gen() {
  local OUT="$1"
  local TAGLINE="$2"

  magick -size 1200x630 radial-gradient:'#0a4a5c'-'#0d0d20' \
    -stroke '#1e2d5e' -strokewidth 1 -fill none \
    -draw 'line 80,120 240,380' \
    -draw 'line 240,380 480,80' \
    -draw 'line 480,80 720,300' \
    -draw 'line 480,80 600,500' \
    -draw 'line 600,500 240,380' \
    -draw 'line 600,500 840,420' \
    -draw 'line 720,300 840,420' \
    -draw 'line 840,420 1050,180' \
    -draw 'line 1050,180 1150,440' \
    -draw 'line 1050,180 960,520' \
    -draw 'line 960,520 840,420' \
    -draw 'line 80,120 160,550' \
    -draw 'line 160,550 360,580' \
    -draw 'line 360,580 600,500' \
    -draw 'line 1150,440 1180,580' \
    -fill '#253060' -stroke none \
    -draw 'circle 80,120 83,120' \
    -draw 'circle 240,380 243,380' \
    -draw 'circle 480,80 483,80' \
    -draw 'circle 720,300 723,300' \
    -draw 'circle 600,500 603,500' \
    -draw 'circle 840,420 843,420' \
    -draw 'circle 1050,180 1053,180' \
    -draw 'circle 1150,440 1153,440' \
    -draw 'circle 960,520 963,520' \
    -draw 'circle 160,550 163,550' \
    -draw 'circle 360,580 363,580' \
    -draw 'circle 1180,580 1183,580' \
    \( "$LOGO" -resize 140x140 \
       \( +clone -background black -shadow 80x16+0+8 \) \
       +swap -background none -layers merge \) \
    -gravity Center -geometry +0-90 -composite \
    -font "$CORMORANT" \
    -pointsize 96 \
    -fill '#ffffff' \
    -gravity Center \
    -annotate +0+30 'mycelium' \
    -font "$INTER" \
    -pointsize 28 \
    -fill '#6b7db3' \
    -gravity Center \
    -annotate +0+108 "$TAGLINE" \
    "$OUT"

  echo "Written: $OUT"
}

gen "$SCRIPT_DIR/../docs/og.png" \
    "coordination layer for multi-agent systems"

LANDING="$SCRIPT_DIR/../../mycelium-io.github.io"
if [ -d "$LANDING" ]; then
  gen "$LANDING/og.png" \
      "coordination layer for multi-agent systems"
else
  echo "Skipping landing page OG (repo not found at $LANDING)"
fi
