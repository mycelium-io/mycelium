#!/usr/bin/env bash
# Generates docs/banner.png
# Requires: ImageMagick 7+, Inter font (brew install font-inter)

LOGO="$(dirname "$0")/../docs/logo.png"
OUT="$(dirname "$0")/../docs/banner.png"
INTER="$HOME/Library/Fonts/InterVariable-Italic.ttf"
DIDOT="/System/Library/Fonts/Supplemental/Didot.ttc"

magick -size 1200x300 xc:'#1a1a2e' \
  -stroke '#1e2d5e' -strokewidth 1 -fill none \
  -draw 'line 80,60 180,200' \
  -draw 'line 180,200 320,40' \
  -draw 'line 320,40 480,150' \
  -draw 'line 420,230 180,200' \
  -draw 'line 420,230 560,80' \
  -draw 'line 560,80 480,150' \
  -draw 'line 560,80 700,200' \
  -draw 'line 700,200 750,260' \
  -draw 'line 700,200 850,120' \
  -draw 'line 850,120 950,80' \
  -draw 'line 950,80 1050,220' \
  -draw 'line 1050,220 1130,50' \
  -draw 'line 1130,50 1180,160' \
  -draw 'line 850,120 1000,280' \
  -draw 'line 100,250 180,200' \
  -draw 'line 100,250 250,280' \
  -draw 'line 250,280 420,230' \
  -fill '#253060' -stroke none \
  -draw 'circle 80,60 83,60' \
  -draw 'circle 180,200 183,200' \
  -draw 'circle 320,40 323,40' \
  -draw 'circle 480,150 483,150' \
  -draw 'circle 420,230 423,230' \
  -draw 'circle 560,80 563,80' \
  -draw 'circle 700,200 703,200' \
  -draw 'circle 750,260 753,260' \
  -draw 'circle 850,120 853,120' \
  -draw 'circle 950,80 953,80' \
  -draw 'circle 1050,220 1053,220' \
  -draw 'circle 1130,50 1132,50' \
  -draw 'circle 1180,160 1183,160' \
  -draw 'circle 1000,280 1003,280' \
  -draw 'circle 100,250 103,250' \
  -draw 'circle 250,280 253,280' \
  \( "$LOGO" -resize 130x130 \
     \( +clone -background black -shadow 60x12+0+6 \) \
     +swap -background none -layers merge \) \
  -gravity North -geometry +0+15 -composite \
  -font "$DIDOT" \
  -pointsize 80 \
  -fill '#ffffff' \
  -gravity North \
  -annotate +0+152 'Mycelium' \
  -font "$INTER" \
  -pointsize 24 \
  -fill '#6b7db3' \
  -gravity North \
  -annotate +0+244 'coordination layer for multi-agent systems' \
  "$OUT"

echo "Banner written to $OUT"
