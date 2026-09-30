#!/usr/bin/env bash
# Record Concord or Accord until a take ends the way its captions say it does.
#
#   bash shotkit/recordings/l9/record.sh concord acme-renewal-q4 acme-renewal-2027
#   bash shotkit/recordings/l9/record.sh accord acme-handoff
#
# Each room name after the flow is one try. The same room name gives the same
# run word for word, so a failed try is only worth repeating under a new name,
# and a name that worked before (acme-renewal-q4 for Concord, acme-handoff for
# Accord) will most likely give the same take again. The backend is restarted
# before each try, because persona teammates keep a model session per room and
# handle, and a room recreated under an old name would otherwise remember the
# last take. Takes land in .shotkit/l9-<flow>-<room>.mp4.
set -uo pipefail
flow=${1:?usage: record.sh concord|accord <room>...}
shift
[ $# -gt 0 ] || { echo "name at least one room to try" >&2; exit 2; }
case $flow in
  concord) want=converged ;;
  accord) want=resolved ;;
  *) echo "flow must be concord or accord" >&2; exit 2 ;;
esac

here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../../.." && pwd)
hub=${HUB:-http://localhost:8000}
backend=${BACKEND_CONTAINER:-mycelium-l9-backend}
cd "$root"

for room in "$@"; do
  docker restart "$backend" >/dev/null
  for _ in $(seq 1 40); do curl -sf "$hub/health" >/dev/null && break; sleep 2; done
  HUB=$hub ROOM=$room uv run --project fastapi-backend python "$here/setup.py" || exit 1
  out=".shotkit/l9-$flow-$room.mp4"
  ROOM=$room OUT=$out bash "$here/$flow.sh" > ".shotkit/l9-$flow-$room.log" 2>&1
  outcome=$(curl -s "$hub/api/rooms/$room/episodes" | python3 -c "
import json, sys
d = json.load(sys.stdin)
d = d if isinstance(d, list) else d.get('episodes', [])
print(next((e.get('outcome') for e in d if (e.get('flow') or {}).get('name') == '$flow'), 'none'))")
  echo "$room: $outcome ($out)"
  [ "$outcome" = "$want" ] && { echo "kept $out"; exit 0; }
done
echo "no try ended $want" >&2
exit 1
