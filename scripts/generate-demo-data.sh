#!/usr/bin/env bash
# Generate demo data for mycelium metrics by sending messages to agents via Matrix.
#
# Prerequisites:
#   - Matrix (Synapse) running on localhost:8008
#   - OpenClaw gateway running with matrix accounts configured
#   - mycelium metrics collect  (OTLP collector running)
#   - OTEL configured: mycelium adapter add openclaw --step=otel
#
# Usage:
#   ./scripts/generate-demo-data.sh [--rounds N] [--clean] [--debug]

set -euo pipefail

SYNAPSE="http://localhost:8008"
ROUNDS=3
CLEAN=false
DEBUG=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --rounds) ROUNDS="${2:-3}"; shift 2 ;;
    --clean)  CLEAN=true; shift ;;
    --debug)  DEBUG=true; shift ;;
    *) shift ;;
  esac
done

CYAN='\033[0;36m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'
RED='\033[0;31m'; BOLD='\033[1m'; DIM='\033[2m'; NC='\033[0m'

step() { echo -e "${CYAN}▸${NC} $1"; }
ok()   { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC} $1"; }
die()  { echo -e "${RED}✗${NC} $1" >&2; exit 1; }
dbg()  { if $DEBUG; then echo -e "  ${DIM}[debug] $1${NC}"; fi; }

echo -e "${BOLD}Mycelium Demo Data Generator${NC}"
echo ""

# ── Check collector is running ────────────────────────────────────────────────
PID_FILE="$HOME/.mycelium/collector.pid"
if [ ! -f "$PID_FILE" ]; then
  # Check if something is actually listening on port 4318 (could be --fg)
  if ss -tln 2>/dev/null | grep -q ':4318 ' || nc -z 127.0.0.1 4318 2>/dev/null; then
    ok "Metrics collector running (foreground or external)"
  else
    warn "Metrics collector not running. Starting it..."
    mycelium metrics collect
    sleep 2
    ok "Metrics collector started"
  fi
else
  ok "Metrics collector running"
fi

# ── Get admin token ───────────────────────────────────────────────────────────
step "Logging in as admin..."
ADMIN_TOKEN=$(curl -sf -X POST "$SYNAPSE/_matrix/client/v3/login" \
  -H 'Content-Type: application/json' \
  -d '{"type":"m.login.password","user":"admin","password":"admin"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])" 2>/dev/null) \
  || die "Could not log in as admin. Check password."
ok "Admin authenticated"

# ── Create/login the sender user ──────────────────────────────────────────────
SENDER="selina"
SENDER_PASS="selina-demo-2026"
SENDER_MX="@${SENDER}:local"

step "Setting up sender account ($SENDER)..."

# Try to register via Synapse admin API (idempotent — 400 if exists)
curl -sf -X PUT "$SYNAPSE/_synapse/admin/v2/users/${SENDER_MX}" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"password\":\"${SENDER_PASS}\",\"admin\":false,\"deactivated\":false}" > /dev/null 2>&1

SENDER_TOKEN=$(curl -sf -X POST "$SYNAPSE/_matrix/client/v3/login" \
  -H 'Content-Type: application/json' \
  -d "{\"type\":\"m.login.password\",\"user\":\"${SENDER}\",\"password\":\"${SENDER_PASS}\"}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])" 2>/dev/null) \
  || die "Could not log in as $SENDER."
ok "Sender $SENDER authenticated"

# ── Discover agents from openclaw ─────────────────────────────────────────────
step "Discovering agents..."
AGENTS=$(python3 -c "
import subprocess, json
r = subprocess.run(['openclaw', 'status', '--json'], capture_output=True, text=True)
data = json.loads(r.stdout)
agents = data.get('agents', {}).get('agents', data.get('agents', []))
if isinstance(agents, dict):
    names = list(agents.keys())
elif isinstance(agents, list):
    names = [a.get('id', a.get('name', '')) if isinstance(a, dict) else str(a) for a in agents]
else:
    names = []
for n in names:
    if n: print(n)
" 2>/dev/null) || die "Could not get agent list from openclaw"

AGENT_COUNT=$(echo "$AGENTS" | wc -l | tr -d ' ')
ok "Found $AGENT_COUNT agents: $(echo $AGENTS | tr '\n' ', ' | sed 's/,$//')"

# ── Clean up old rooms if requested ───────────────────────────────────────────
if $CLEAN; then
  step "Cleaning up rooms..."
  for agent in $AGENTS; do
    AGENT_TOKEN=$(python3 -c "
import json
cfg = json.load(open('/home/ubuntu/.openclaw/openclaw.json'))
acct = cfg['channels']['matrix']['accounts'].get('${agent}', {})
print(acct.get('accessToken', ''))
" 2>/dev/null)
    if [ -z "$AGENT_TOKEN" ]; then continue; fi

    # Leave all rooms for this agent
    ROOMS=$(curl -sf -H "Authorization: Bearer $AGENT_TOKEN" \
      "$SYNAPSE/_matrix/client/v3/joined_rooms" 2>/dev/null | \
      python3 -c "import sys,json; print('\n'.join(json.load(sys.stdin).get('joined_rooms',[])))" 2>/dev/null)
    for room in $ROOMS; do
      curl -sf -X POST "$SYNAPSE/_matrix/client/v3/rooms/${room}/leave" \
        -H "Authorization: Bearer $AGENT_TOKEN" \
        -H "Content-Type: application/json" \
        -d '{}' > /dev/null 2>&1
      dbg "$agent left $room"
    done
    ok "  $agent left all rooms"
  done

  # Sender and admin leave all rooms too
  for cleanup_user_label in "$SENDER:$SENDER_TOKEN" "admin:$ADMIN_TOKEN"; do
    cleanup_label="${cleanup_user_label%%:*}"
    cleanup_token="${cleanup_user_label#*:}"
    CLEANUP_ROOMS=$(curl -sf -H "Authorization: Bearer $cleanup_token" \
      "$SYNAPSE/_matrix/client/v3/joined_rooms" 2>/dev/null | \
      python3 -c "import sys,json; print('\n'.join(json.load(sys.stdin).get('joined_rooms',[])))" 2>/dev/null)
    for room in $CLEANUP_ROOMS; do
      curl -sf -X POST "$SYNAPSE/_matrix/client/v3/rooms/${room}/leave" \
        -H "Authorization: Bearer $cleanup_token" \
        -H "Content-Type: application/json" \
        -d '{}' > /dev/null 2>&1
    done
    ok "  $cleanup_label left all rooms"
  done

  echo ""
  warn "All rooms cleared. Restart the openclaw gateway to pick up new rooms:"
  echo "    systemctl --user restart openclaw-gateway.service"
  echo ""
  echo "  Then re-run this script without --clean."
  exit 0
fi

# ── Prompts to send ───────────────────────────────────────────────────────────
PROMPTS=(
  "What is the capital of France? Reply in one sentence."
  "Explain what a REST API is in two sentences."
  "List 3 benefits of microservices architecture. Be brief."
  "What is the difference between TCP and UDP? One paragraph."
  "Describe the CAP theorem in simple terms."
  "What are environment variables used for? Brief answer."
  "Name 3 common HTTP status codes and what they mean."
  "What is containerization? Explain briefly."
  "What does CI/CD stand for and why is it useful? Two sentences."
  "What is the purpose of a load balancer? Brief answer."
)

# ── Send messages ─────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}Sending $ROUNDS rounds of messages to each agent...${NC}"
echo ""

MSG_IDX=0
TOTAL_SENT=0
TOTAL_REPLIED=0

# count_messages_from <room_id> <user_id> <token> → prints the count
count_messages_from() {
  local room="$1" user="$2" token="$3"
  curl -sf -H "Authorization: Bearer $token" \
    "$SYNAPSE/_matrix/client/v3/rooms/${room}/messages?dir=b&limit=100" 2>/dev/null | \
    python3 -c "
import sys, json
data = json.load(sys.stdin)
count = sum(1 for e in data.get('chunk', [])
            if e.get('type') == 'm.room.message' and e.get('sender') == '${user}')
print(count)
" 2>/dev/null || echo "0"
}

for agent in $AGENTS; do
  step "Setting up room for $agent..."

  # Get the agent's access token from openclaw.json
  AGENT_TOKEN=$(python3 -c "
import json
cfg = json.load(open('/home/ubuntu/.openclaw/openclaw.json'))
acct = cfg['channels']['matrix']['accounts'].get('${agent}', {})
print(acct.get('accessToken', ''))
" 2>/dev/null)

  if [ -z "$AGENT_TOKEN" ]; then
    warn "No access token for $agent — skipping"
    continue
  fi
  dbg "Got token for $agent"

  # List the agent's current rooms
  AGENT_ROOMS=$(curl -sf -H "Authorization: Bearer $AGENT_TOKEN" \
    "$SYNAPSE/_matrix/client/v3/joined_rooms" 2>/dev/null | \
    python3 -c "import sys,json; print('\n'.join(json.load(sys.stdin).get('joined_rooms',[])))" 2>/dev/null)

  ROOM_COUNT=$(echo "$AGENT_ROOMS" | grep -c '.' || true)
  dbg "$agent is in $ROOM_COUNT rooms"

  if [ "$ROOM_COUNT" -eq 0 ] || [ -z "$AGENT_ROOMS" ]; then
    # No rooms — create a DM as the sender, inviting the agent
    dbg "No rooms — creating DM as $SENDER inviting $agent"
    ROOM_ID=$(curl -sf -X POST "$SYNAPSE/_matrix/client/v3/createRoom" \
      -H "Authorization: Bearer $SENDER_TOKEN" \
      -H "Content-Type: application/json" \
      -d "{\"is_direct\":true,\"invite\":[\"@${agent}:local\"],\"preset\":\"trusted_private_chat\"}" \
      | python3 -c "import sys,json; print(json.load(sys.stdin)['room_id'])" 2>/dev/null)

    if [ -z "$ROOM_ID" ]; then
      warn "Could not create room for $agent — skipping"
      continue
    fi

    # Accept invite as the agent
    curl -sf -X POST "$SYNAPSE/_matrix/client/v3/rooms/${ROOM_ID}/join" \
      -H "Authorization: Bearer $AGENT_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{}' > /dev/null 2>&1
    sleep 3
    ok "Created new DM $ROOM_ID ($SENDER → $agent)"
  else
    # Use the first room the agent is in; make sure the sender is also in it
    ROOM_ID=$(echo "$AGENT_ROOMS" | head -1)
    dbg "Trying agent's first room: $ROOM_ID"

    # Check if the sender is already in this room
    SENDER_IN=$(curl -sf -H "Authorization: Bearer $SENDER_TOKEN" \
      "$SYNAPSE/_matrix/client/v3/rooms/${ROOM_ID}/joined_members" 2>/dev/null | \
      python3 -c "
import sys,json
d = json.load(sys.stdin)
print('yes' if '${SENDER_MX}' in d.get('joined',{}) else 'no')
" 2>/dev/null || echo "no")

    if [ "$SENDER_IN" != "yes" ]; then
      dbg "$SENDER not in room — inviting and joining"
      curl -sf -X POST "$SYNAPSE/_matrix/client/v3/rooms/${ROOM_ID}/invite" \
        -H "Authorization: Bearer $AGENT_TOKEN" \
        -H "Content-Type: application/json" \
        -d "{\"user_id\":\"${SENDER_MX}\"}" > /dev/null 2>&1

      curl -sf -X POST "$SYNAPSE/_matrix/client/v3/rooms/${ROOM_ID}/join" \
        -H "Authorization: Bearer $SENDER_TOKEN" \
        -H "Content-Type: application/json" \
        -d '{}' > /dev/null 2>&1
      sleep 2
    fi

    ok "Using room $ROOM_ID for $agent"
  fi

  # Debug: show room members
  if $DEBUG; then
    MEMBERS_LIST=$(curl -sf -H "Authorization: Bearer $SENDER_TOKEN" \
      "$SYNAPSE/_matrix/client/v3/rooms/${ROOM_ID}/joined_members" 2>/dev/null | \
      python3 -c "import sys,json; print(', '.join(json.load(sys.stdin).get('joined',{}).keys()))" 2>/dev/null)
    dbg "Room members: $MEMBERS_LIST"
  fi

  AGENT_REPLIES_BEFORE=$(count_messages_from "$ROOM_ID" "@${agent}:local" "$SENDER_TOKEN")
  dbg "Agent messages before: $AGENT_REPLIES_BEFORE"

  for ((round=1; round<=ROUNDS; round++)); do
    PROMPT="${PROMPTS[$MSG_IDX % ${#PROMPTS[@]}]}"
    MSG_IDX=$((MSG_IDX + 1))
    TXN_ID="demo_${SENDER}_${agent}_${round}_$(date +%s%N)"
    TOTAL_SENT=$((TOTAL_SENT + 1))

    echo -e "  ${DIM}[$agent round $round/$ROUNDS]${NC} $PROMPT"

    # Send as the sender user (not admin, not an agent)
    SEND_RESULT=$(curl -sf -X PUT "$SYNAPSE/_matrix/client/v3/rooms/${ROOM_ID}/send/m.room.message/${TXN_ID}" \
      -H "Authorization: Bearer $SENDER_TOKEN" \
      -H "Content-Type: application/json" \
      -d "{\"msgtype\":\"m.text\",\"body\":\"${PROMPT}\"}" 2>&1)
    dbg "Send result: $SEND_RESULT"

    # Poll for a response (up to 90s, check every 10s)
    echo -ne "  ${DIM}  waiting for response..."
    REPLIED=false
    for ((wait=0; wait<9; wait++)); do
      sleep 10
      CURRENT=$(count_messages_from "$ROOM_ID" "@${agent}:local" "$SENDER_TOKEN")
      EXPECTED=$((AGENT_REPLIES_BEFORE + round))
      dbg "poll: current=$CURRENT expected>=$EXPECTED"
      if [ "$CURRENT" -ge "$EXPECTED" ] 2>/dev/null; then
        REPLIED=true
        break
      fi
      echo -ne "."
    done
    echo -e "${NC}"

    if [ "$REPLIED" = true ]; then
      ok "  $agent replied (round $round)"
      TOTAL_REPLIED=$((TOTAL_REPLIED + 1))
    else
      warn "  $agent did not reply within 90s (round $round)"
      if $DEBUG; then
        # Check if the agent replied in any OTHER room
        dbg "Checking all agent rooms for replies..."
        ALL_ROOMS=$(curl -sf -H "Authorization: Bearer $AGENT_TOKEN" \
          "$SYNAPSE/_matrix/client/v3/joined_rooms" 2>/dev/null | \
          python3 -c "import sys,json; print('\n'.join(json.load(sys.stdin).get('joined_rooms',[])))" 2>/dev/null)
        for check_room in $ALL_ROOMS; do
          if [ "$check_room" = "$ROOM_ID" ]; then continue; fi
          MSGS=$(curl -sf -H "Authorization: Bearer $AGENT_TOKEN" \
            "$SYNAPSE/_matrix/client/v3/rooms/${check_room}/messages?dir=b&limit=5" 2>/dev/null | \
            python3 -c "
import sys, json
data = json.load(sys.stdin)
for e in data.get('chunk', []):
    if e.get('type') == 'm.room.message' and e.get('sender') == '@${agent}:local':
        body = e.get('content',{}).get('body','')[:60]
        print(f'  → {check_room}: {body}')
        break
" 2>/dev/null)
          if [ -n "$MSGS" ]; then
            dbg "Found agent reply in different room!"
            echo -e "$MSGS"
          fi
        done
      fi
    fi
  done
  echo ""
done

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}Message summary:${NC}"
echo -e "  Sent:     $TOTAL_SENT"
echo -e "  Replied:  $TOTAL_REPLIED"
if [ "$TOTAL_REPLIED" -eq 0 ]; then
  warn "No replies received — check openclaw gateway logs"
elif [ "$TOTAL_REPLIED" -lt "$TOTAL_SENT" ]; then
  warn "Some messages got no reply"
else
  ok "All messages received replies"
fi

# ── Show results ──────────────────────────────────────────────────────────────
echo -e "${BOLD}Waiting for telemetry to flush (10s)...${NC}"
sleep 10

echo ""
echo -e "${BOLD}Current metrics:${NC}"
echo ""
mycelium metrics show
