#!/usr/bin/env bash
# One take of Accord (members agree on what the task is), live in the real app.
# The room must already be set up (setup.py). record.sh runs this for you.
#
#   ROOM=acme-handoff APP_URL=http://localhost:51268 OUT=.shotkit/accord.mp4 \
#     bash shotkit/recordings/l9/accord.sh
set -euo pipefail
cd "$(dirname "$0")/../../.."
node shotkit/bin/shot.mjs video "/room/${ROOM:-acme-renewal}" \
  --base-url "${APP_URL:-http://localhost:3000}" \
  --out "${OUT:-.shotkit/accord.mp4}" \
  --width 1440 --height 900 --format mp4 --caption-at top \
  --storage mycelium.principal=morgan --storage mycelium.name-asked=1 \
  --action-timeout 300000 --max-seconds 150 --tail 2500 \
  --do "caption:Before work starts, make sure everyone means the same thing by the task." \
  --do "hold:2600" \
  --do "click:Board" \
  --do "click:[data-board-row=\"memory:work/acme-renewal-handoff\"]" \
  --do "caption:One message starts Accord. Nobody leads it." \
  --do "click:textarea[placeholder^=\"Reply in\"]" \
  --do "typekeys:@conductor accord @sales @success @finance @legal: Plan the Acme renewal handoff." \
  --do "press:Enter" \
  --do "caption:Everyone labels what they think the task is: its aim, its limits, what's out of scope." \
  --do "speed:5" \
  --do "wait:text=/Round 1: \\d+ new point/" \
  --do "speed:1" \
  --do "caption:Code merges the points and shows them. Everyone adds what's missing." \
  --do "zoom:text=/Round 1: \\d+ new point/@1.4" \
  --do "hold:3500" \
  --do "zoomout" \
  --do "speed:5" \
  --do "wait:text=/Nobody added anything new|Points were still coming/" \
  --do "speed:1" \
  --do "hold:1500" \
  --do "caption:Then the words: a word two people mean differently is flagged, not settled." \
  --do "speed:5" \
  --do "wait:text=/accord (done|rejected)/" \
  --do "speed:1" \
  --do "hold:1500" \
  --do "caption:Nobody leads and nobody votes. What doesn't line up becomes an open item." \
  --do "zoom:text=/Shared summary: /@1.4" \
  --do "hold:4000" \
  --do "zoomout" \
  --do "caption:The shared summary is saved to the room's memory, next to the task." \
  --do "click:context/summary/acme-renewal-handoff" \
  --do "hold:5000" \
  --do "hold:2500"
