#!/usr/bin/env bash
# One take of Concord (members agree on a decision), live in the real app.
# The room must already be set up (setup.py). record.sh runs this for you.
#
#   ROOM=acme-renewal-q4 APP_URL=http://localhost:51268 OUT=.shotkit/concord.mp4 \
#     bash shotkit/recordings/l9/concord.sh
set -euo pipefail
cd "$(dirname "$0")/../../.."
node shotkit/bin/shot.mjs video "/room/${ROOM:-acme-renewal}" \
  --base-url "${APP_URL:-http://localhost:3000}" \
  --out "${OUT:-.shotkit/concord.mp4}" \
  --width 1440 --height 900 --format mp4 --caption-at top \
  --storage mycelium.principal=morgan --storage mycelium.name-asked=1 \
  --action-timeout 300000 --max-seconds 150 --tail 2500 \
  --do "caption:Four agents share one task, and they don't agree on the renewal offer." \
  --do "hold:2600" \
  --do "click:Board" \
  --do "click:[data-board-row=\"work/acme-renewal-offer\"]" \
  --do "caption:Ask them to agree. One message starts the flow." \
  --do "click:textarea[placeholder^=\"Reply in\"]" \
  --do "typekeys:@conductor concord @~success @~finance @~sales @~legal: Decide the renewal offer for Acme." \
  --do "press:Enter" \
  --do "eval:(window.__follow ||= setInterval(() => { const b = [...document.querySelectorAll('button')].find((x) => x.textContent.includes('Jump to latest')); if (b) b.click(); }, 1000), 'following the thread')" \
  --do "caption:Everyone suggests an option, then rates every option from 0 to 100." \
  --do "speed:5" \
  --do "wait:table[aria-label^=\"Ratings\"]" \
  --do "speed:1" \
  --do "caption:Code picks the option the least happy agent likes best. Not a model." \
  --do "zoom:table[aria-label^=\"Ratings\"]@1.5" \
  --do "hold:3800" \
  --do "zoomout" \
  --do "caption:If anyone is below the bar, the least happy suggests a fix, and everyone rates it." \
  --do "speed:5" \
  --do "wait:text=/concord\\s*(converged|rejected)/" \
  --do "speed:1" \
  --do "caption:It stops once everyone clears the bar, and says what it went with." \
  --do "zoom:text=/pick: .+, everyone at \\d+\\+/ >> nth=-1@1.4" \
  --do "hold:3800" \
  --do "zoomout" \
  --do "caption:The decision is saved to the room's memory, next to the task." \
  --do "click:text=/^acme-renewal-offer\\.md$/" \
  --do "hold:5000"
