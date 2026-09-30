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
  --do "caption:One message starts Accord. The first person named leads." \
  --do "click:textarea[placeholder^=\"Reply in\"]" \
  --do "typekeys:@conductor accord @sales @success @finance @legal: Plan the Acme renewal handoff." \
  --do "press:Enter" \
  --do "caption:Everyone says what the task is, what's out of scope, and what done means." \
  --do "speed:5" \
  --do "wait:text=/merge → /" \
  --do "speed:1" \
  --do "hold:1500" \
  --do "caption:The lead combines them into one shared summary." \
  --do "speed:5" \
  --do "wait:text=/on to lock/" \
  --do "speed:1" \
  --do "zoom:xpath=(//div[@data-testid='conductor-row'][contains(., 'on to lock')])[1]/preceding-sibling::div[1]@1.25" \
  --do "hold:5000" \
  --do "zoomout" \
  --do "caption:Then everyone accepts it or objects. An objection sends it back to the lead." \
  --do "speed:5" \
  --do "wait:text=/accord (done|rejected)/" \
  --do "speed:1" \
  --do "hold:1500" \
  --do "caption:Once nobody objects, the summary is agreed and work can start." \
  --do "zoom:text=/accord (done|rejected)/@1.4" \
  --do "hold:3800" \
  --do "zoomout" \
  --do "hold:2500"
