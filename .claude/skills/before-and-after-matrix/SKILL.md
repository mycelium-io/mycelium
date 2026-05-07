---
name: before-and-after-matrix
description: End-to-end smoke test for cross-channel coordination. Spins up two ephemeral OpenClaw agents wired to local Matrix Synapse + mycelium-room, kicks off a structured negotiation from a Matrix DM, and verifies the consensus summary auto-delivers back to the user's Matrix DM. Use when validating PR #221's return-trip mechanism still works, or after touching plugin/channel code, or to repro the original "agents go silent" bug class.
argument-hint: "<scenario name or experiment file> (optional)"
---

# Before-and-After Matrix

Tests the **cross-channel coordination** path end-to-end:

1. User in their home channel (Matrix DM) tells their agent to coordinate with another agent
2. Agent runs `mycelium session join` from inside that DM
3. CFN drives multi-round negotiation in a session sub-room
4. The Mycelium plugin auto-delivers the consensus summary back to the user's Matrix DM

The **ship gate** is step 4: did the user actually see the result land in their Matrix DM, without the agent having to remember to call `sessions_send`?

The negotiation can happen in any room name — the channel plugin watches every active session sub-room and routes ticks by `participant_id`, not by room. The skill exercises that: agents negotiate in a fresh per-test room (`$EXP_ROOM`), and the return-trip still lands.

**You are the test harness.** You set up Synapse users, wire OpenClaw, seed scenarios, observe transcripts, evaluate. The agents do the negotiating.

## Phase 0: Prerequisites

Before anything else, verify the stack. Run each check and stop if any fail.

```bash
# 1. Mycelium CLI
mycelium --version
# If missing: pip install mycelium (or pipx install mycelium)

# 2. Resolve the backend URL — NEVER hardcode a port
MYCELIUM_API_URL=$(python3 -c "
import toml, os
cfg = toml.load(os.path.expanduser('~/.mycelium/config.toml'))
print(cfg.get('server', {}).get('api_url', 'http://localhost:8000'))
")
echo "Backend URL: $MYCELIUM_API_URL"

# 3. Mycelium stack running (backend + AgensGraph + CFN)
curl -sf "$MYCELIUM_API_URL/health" | python3 -m json.tool
# Should show status=ok. If not: mycelium install && mycelium up

# 4. OpenClaw installed + gateway up
openclaw --version && openclaw channels status
# Should show "Gateway reachable". If not: openclaw gateway start

# 5. Local Matrix Synapse running
docker ps --format '{{.Names}}' | grep -E 'matrix|synapse' || echo "no matrix container running"
# Synapse must be reachable on localhost (default 8008). The openclaw-matrix
# container in the mycelium-cli docker stack is the canonical one.
curl -sf http://localhost:8008/_matrix/client/v3/login | python3 -m json.tool >/dev/null \
  && echo "matrix login endpoint OK" \
  || { echo "matrix not reachable on localhost:8008"; exit 1; }

# 6. Mycelium repo path (we read SKILL.md and verify install paths from here)
MYCELIUM_REPO=$(pwd)
ls "$MYCELIUM_REPO/mycelium-cli/src/mycelium/adapters/openclaw/mycelium/plugin/index.ts" 2>/dev/null \
  && echo "Repo OK: $MYCELIUM_REPO" \
  || { echo "ERROR: not in the mycelium repo"; exit 1; }
```

If any prerequisite fails, fix it before proceeding. Throughout this skill, use `$MYCELIUM_API_URL` for backend requests; never hardcode a port.

### 0a. Verify Synapse registration + admin

This skill creates throwaway Matrix users via the public registration endpoint. Confirm registration is open on this Synapse:

```bash
docker exec $(docker ps --format '{{.Names}}' | grep -E 'matrix|synapse' | head -1) \
  grep -E "enable_registration|server_name" /data/homeserver.yaml
# Need: enable_registration: true (or enable_registration_without_verification: true).
# Capture server_name — Matrix user IDs will be @<name>:<server_name>.
```

Stash the server name:

```bash
SYNAPSE_CONTAINER=$(docker ps --format '{{.Names}}' | grep -E 'matrix|synapse' | head -1)
SYNAPSE_SERVER=$(docker exec "$SYNAPSE_CONTAINER" grep "^server_name:" /data/homeserver.yaml | awk '{print $2}' | tr -d '"')
echo "SYNAPSE_SERVER=$SYNAPSE_SERVER"
```

If registration is locked down, you'll need either the `registration_shared_secret` from `homeserver.yaml` or pre-existing accounts. The version in this skill assumes open registration; adapt as needed.

## Phase 0.5: Choose experiment LLM & API key

Same logic as the standard `before-and-after` skill — default to Haiku unless the user explicitly wants Sonnet. Each negotiation fires 10–40+ LLM calls; cost differs ~12×.

```bash
CONFIGURED_MODEL=$(python3 -c "
import json, os
p = os.path.expanduser('~/.openclaw/openclaw.json')
try:
    cfg = json.load(open(p))
    print(cfg.get('agents', {}).get('defaults', {}).get('model', ''))
except Exception:
    print('')
")
echo "Currently configured model: ${CONFIGURED_MODEL:-'(none)'}"
```

Use `AskUserQuestion` to pick: Haiku (default) / Sonnet / configured / different key.
Set `EXP_MODEL` accordingly. Echo the choice into the transcript:

```bash
echo "Using model: $EXP_MODEL"
```

## Phase 1: Setup

### 1a. Generate experiment IDs + handles

```bash
EXP_ID="xch-$(date +%s | tail -c 5)"  # e.g. xch-4821
EXP_AGENT_A="${EXP_ID}-agent-a"
EXP_AGENT_B="${EXP_ID}-agent-b"
EXP_HUMAN="${EXP_ID}-human"
EXP_ROOM="${EXP_ID}"
echo "EXP_ID=$EXP_ID"
echo "EXP_AGENT_A=$EXP_AGENT_A  EXP_AGENT_B=$EXP_AGENT_B  EXP_HUMAN=$EXP_HUMAN"
echo "EXP_ROOM=$EXP_ROOM"
```

### 1b. Register Matrix users (3 of them: human + 2 agents)

Public registration with the `m.login.dummy` flow. Captures the access token from each registration response — needed to log the agent into Matrix from OpenClaw and to send DMs as the human in later phases.

```bash
declare -A MATRIX_TOKENS
for u in "$EXP_HUMAN" "$EXP_AGENT_A" "$EXP_AGENT_B"; do
  RESP=$(curl -s -X POST "http://localhost:8008/_matrix/client/v3/register" \
    -H "Content-Type: application/json" \
    -d "{\"username\":\"$u\",\"password\":\"poc-pass-$u\",\"auth\":{\"type\":\"m.login.dummy\"},\"inhibit_login\":false,\"device_id\":\"openclaw\"}")
  TOKEN=$(echo "$RESP" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('access_token',''))
")
  if [ -z "$TOKEN" ]; then
    echo "FAILED to register $u: $RESP"; exit 1
  fi
  MATRIX_TOKENS[$u]="$TOKEN"
  echo "$u  →  @$u:$SYNAPSE_SERVER  (token=${TOKEN:0:20}…)"
done
HUMAN_TOKEN="${MATRIX_TOKENS[$EXP_HUMAN]}"
AGENT_A_TOKEN="${MATRIX_TOKENS[$EXP_AGENT_A]}"
AGENT_B_TOKEN="${MATRIX_TOKENS[$EXP_AGENT_B]}"
```

> **Skill gotcha — registration is one-shot.** If the username already exists, registration returns 400. Either parse responses defensively or always use a fresh `${EXP_ID}-` prefix per run. We default to fresh prefixes.

### 1c. Create the OpenClaw test agents

```bash
for a in "$EXP_AGENT_A" "$EXP_AGENT_B"; do
  openclaw agents add "$a" \
    --non-interactive \
    --workspace ~/.openclaw/workspaces/"$a" \
    --model "$EXP_MODEL"
done
```

### 1d. Apply OpenClaw config invariants

These are the four invariants that, if missed, cause silent or noisy failures. **All four are required**; doctor doesn't catch the combination today (see issue #220 for status).

```bash
python3 - <<PYEOF
import json, os
p = os.path.expanduser('~/.openclaw/openclaw.json')
cfg = json.load(open(p))
target_ids = {"$EXP_AGENT_A", "$EXP_AGENT_B"}
for a in cfg['agents']['list']:
    if a.get('id') in target_ids:
        # 1. Sandbox off — needed for the agent to see host binaries
        a['sandbox'] = {'mode': 'off'}
        # 2. Exec on the gateway, not the sandbox
        a.setdefault('tools', {}).setdefault('exec', {})
        a['tools']['exec']['host'] = 'gateway'
        a['tools']['exec']['security'] = 'full'  # for testing; tighten with allowlist in prod
json.dump(cfg, open(p, 'w'), indent=2)
print('agent invariants applied')
PYEOF
```

Three more, applied via CLI:

```bash
# 3. Allowlist the mycelium binary so agents can run it without per-call approval prompts
openclaw approvals allowlist add --agent "$EXP_AGENT_A" "$HOME/.local/bin/mycelium"
openclaw approvals allowlist add --agent "$EXP_AGENT_B" "$HOME/.local/bin/mycelium"

# 4. Enable elevated mode so the human user can grant elevated commands via DM
python3 - <<'PYEOF'
import json, os
p = os.path.expanduser('~/.openclaw/openclaw.json')
cfg = json.load(open(p))
cfg.setdefault('tools', {}).setdefault('elevated', {})
cfg['tools']['elevated']['enabled'] = True
af = cfg['tools']['elevated'].setdefault('allowFrom', {})
af['matrix'] = list(set((af.get('matrix') or []) + [f"@{os.environ['EXP_HUMAN']}:{os.environ['SYNAPSE_SERVER']}"]))
json.dump(cfg, open(p, 'w'), indent=2)
print('elevated allowFrom updated')
PYEOF
```

### 1e. Wire Matrix accounts for each agent

```bash
openclaw channels add --channel matrix --account "$EXP_AGENT_A" \
  --homeserver http://localhost:8008 \
  --user-id "@$EXP_AGENT_A:$SYNAPSE_SERVER" \
  --access-token "$AGENT_A_TOKEN" \
  --device-name openclaw

openclaw channels add --channel matrix --account "$EXP_AGENT_B" \
  --homeserver http://localhost:8008 \
  --user-id "@$EXP_AGENT_B:$SYNAPSE_SERVER" \
  --access-token "$AGENT_B_TOKEN" \
  --device-name openclaw
```

> **Skill gotcha — SSRF guard blocks `localhost`.** OpenClaw's HTTP guard rejects loopback/RFC1918 addresses by default. Per-account opt-in:

```bash
python3 - <<PYEOF
import json, os
p = os.path.expanduser('~/.openclaw/openclaw.json')
cfg = json.load(open(p))
for acct_id in ('$EXP_AGENT_A', '$EXP_AGENT_B'):
    acct = cfg['channels']['matrix']['accounts'][acct_id]
    acct['allowPrivateNetwork'] = True
    # Auto-accept invite-on-DM-create from the human user
    acct['autoJoin'] = 'always'
json.dump(cfg, open(p, 'w'), indent=2)
print('matrix accounts updated: allowPrivateNetwork + autoJoin')
PYEOF
```

### 1f. Bind agents to their Matrix accounts

Without this, Matrix DMs are routed to the default agent (typically `main`), which may be sandboxed and won't have the experiment persona. The agent appears to "respond in character" by reading the prompt — but it's actually `main` reading SOUL.md from the wrong workspace.

```bash
openclaw agents bind --agent "$EXP_AGENT_A" --bind "matrix:$EXP_AGENT_A"
openclaw agents bind --agent "$EXP_AGENT_B" --bind "matrix:$EXP_AGENT_B"
openclaw agents bindings   # confirm both show up
```

### 1g. Create the Mycelium room + register the channel

The plugin watches every active session sub-room and routes ticks by `participant_id`, so `channels.mycelium-room.room` does not have to match the room your prompt names. It only sets the default for outbound `mycelium room send` calls and unaddressed broadcasts. Pick anything sensible.

```bash
mycelium room create "$EXP_ROOM"

python3 - <<PYEOF
import json, os
p = os.path.expanduser('~/.openclaw/openclaw.json')
cfg = json.load(open(p))
cfg.setdefault('channels', {})['mycelium-room'] = {
    'enabled': True,
    'backendUrl': '$MYCELIUM_API_URL',
    'room': '$EXP_ROOM',
    'agents': ['$EXP_AGENT_A', '$EXP_AGENT_B'],
    'requireMention': True,
}
json.dump(cfg, open(p, 'w'), indent=2)
print('mycelium-room channel registered with default room $EXP_ROOM')
PYEOF
```

### 1h. Write personas

Derive personas from the user's scenario; `SOUL.md` per agent. Same guidance as the standard `before-and-after` skill — concrete experience, specific data, clear priorities.

```bash
cat > ~/.openclaw/workspaces/"$EXP_AGENT_A"/SOUL.md <<EOF
{persona text — who agent-a is, what they value, specific experience/data}
EOF

cat > ~/.openclaw/workspaces/"$EXP_AGENT_B"/SOUL.md <<EOF
{persona text — who agent-b is, what they value, specific experience/data}
EOF
```

### 1i. Restart and verify

```bash
openclaw gateway restart
sleep 6

# Both Matrix accounts should be running
openclaw channels status | grep -E "Matrix.*$EXP_ID"

# Mycelium-room channel should be configured for our room
grep "SSE connected.*$EXP_ROOM" /tmp/openclaw/openclaw-$(date +%Y-%m-%d).log | tail -1
```

If the matrix accounts show `error:Blocked hostname` or the SSE line isn't there, walk back through 1d–1h.

## Phase 2: Pair the human → agent DMs

OpenClaw's DM-pairing security model requires explicit approval the first time a sender DMs an agent. This skill auto-handles it — the test harness sees the pairing-code reply and approves it.

For each agent, create a DM, send a sanity ping, capture the pairing code from the agent's auto-reply, approve.

```bash
HUMAN_USER="@$EXP_HUMAN:$SYNAPSE_SERVER"
declare -A AGENT_DM_ROOMS

for agent in "$EXP_AGENT_A" "$EXP_AGENT_B"; do
  # Create DM
  RESP=$(curl -s -X POST "http://localhost:8008/_matrix/client/v3/createRoom" \
    -H "Authorization: Bearer $HUMAN_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"is_direct\":true,\"invite\":[\"@$agent:$SYNAPSE_SERVER\"],\"preset\":\"trusted_private_chat\"}")
  ROOM=$(echo "$RESP" | python3 -c "import sys, json; print(json.load(sys.stdin).get('room_id',''))")
  AGENT_DM_ROOMS[$agent]="$ROOM"

  # Send sanity ping
  ROOM_ENC=$(python3 -c "import urllib.parse, sys; print(urllib.parse.quote(sys.argv[1], safe=''))" "$ROOM")
  TXN=$(date +%s%N)
  curl -s -X PUT "http://localhost:8008/_matrix/client/v3/rooms/$ROOM_ENC/send/m.room.message/$TXN" \
    -H "Authorization: Bearer $HUMAN_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"msgtype":"m.text","body":"sanity ping"}' >/dev/null

  # Wait up to 60s for pairing-code reply, then approve
  for i in $(seq 1 20); do
    sleep 3
    BODY=$(curl -s "http://localhost:8008/_matrix/client/v3/rooms/$ROOM_ENC/messages?dir=b&limit=3" \
      -H "Authorization: Bearer $HUMAN_TOKEN" \
      | python3 -c "
import sys, json
d = json.loads(sys.stdin.read(), strict=False)
for ev in d.get('chunk', []):
    if ev.get('type') == 'm.room.message' and ev.get('sender') == '@$agent:$SYNAPSE_SERVER':
        print(ev.get('content',{}).get('body',''))
        break
")
    CODE=$(echo "$BODY" | grep -oE 'Pairing code:[^A-Z0-9]*([A-Z0-9]{8})' | grep -oE '[A-Z0-9]{8}' | head -1)
    if [ -n "$CODE" ]; then
      echo "  $agent  pairing code = $CODE → approving"
      openclaw pairing approve matrix "$CODE"
      break
    fi
  done
done

# Send a follow-up sanity message to each agent and confirm it actually replies in-character
for agent in "$EXP_AGENT_A" "$EXP_AGENT_B"; do
  ROOM="${AGENT_DM_ROOMS[$agent]}"
  ROOM_ENC=$(python3 -c "import urllib.parse, sys; print(urllib.parse.quote(sys.argv[1], safe=''))" "$ROOM")
  TXN=$(date +%s%N)
  curl -s -X PUT "http://localhost:8008/_matrix/client/v3/rooms/$ROOM_ENC/send/m.room.message/$TXN" \
    -H "Authorization: Bearer $HUMAN_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"msgtype":"m.text","body":"hello — confirm channel alive with one short sentence"}' >/dev/null
done
sleep 25
# Validate: the most-recent agent reply must NOT be a pairing prompt anymore
for agent in "$EXP_AGENT_A" "$EXP_AGENT_B"; do
  ROOM="${AGENT_DM_ROOMS[$agent]}"
  ROOM_ENC=$(python3 -c "import urllib.parse, sys; print(urllib.parse.quote(sys.argv[1], safe=''))" "$ROOM")
  curl -s "http://localhost:8008/_matrix/client/v3/rooms/$ROOM_ENC/messages?dir=b&limit=3" \
    -H "Authorization: Bearer $HUMAN_TOKEN" \
    | python3 -c "
import sys, json
d = json.loads(sys.stdin.read(), strict=False)
for ev in d.get('chunk', []):
    if ev.get('type') == 'm.room.message' and ev.get('sender') == '@$agent:$SYNAPSE_SERVER':
        body = ev.get('content',{}).get('body','')
        ok = 'Pairing code' not in body and 'access not configured' not in body
        print(f\"$agent: {'✓ alive' if ok else '✗ still paired-out'} — {body[:80]}\")
        break
"
done
```

> **Skill gotcha — pairing codes regenerate on each DM attempt that arrives before the previous code was approved.** If your approval call lands AFTER a second prompt was sent, the new code invalidates the old. The loop above approves the most-recent code; if that races, send another sanity ping and retry the loop.

## Phase 3: Trigger the negotiation

### 3a. Compose the seed prompt

The prompt should explicitly tell the agents NOT to use `session await` (it would block the gateway thread). For OpenClaw this is the right guidance — channel plugin handles wakeup.

```bash
PROMPT_TEMPLATE='You are participating in a distributed cross-agent test. Topic: $SCENARIO_PROMPT. Coordinate with the other agent in the room "$EXP_ROOM" via Mycelium structured negotiation.

You are AGENT_PERSONA. Your full position is in your SOUL.md.

Run EXACTLY these commands — do NOT run any others:

1. Join the coordination session as yourself:
     mycelium session join --handle YOUR_HANDLE --room $EXP_ROOM -m "<your position in one sentence>"

2. Do NOT run mycelium session await. The Mycelium channel plugin wakes you when CognitiveEngine addresses you — session await would block the gateway thread.

3. When a tick arrives, respond via the CLI:
     mycelium negotiate respond accept --room $EXP_ROOM --handle YOUR_HANDLE
   or, only if the tick says can_counter_offer: true:
     mycelium negotiate propose ISSUE=VALUE ISSUE=VALUE --room $EXP_ROOM --handle YOUR_HANDLE

4. After responding, return control. Continue until the negotiation concludes.

5. The result will be auto-delivered back to this DM by the Mycelium plugin — you do NOT need to relay it yourself.

Briefly explain your reasoning before each CLI command.'
```

Substitute per-agent values and send to each Matrix DM.

### 3b. Send the prompts

```bash
for agent in "$EXP_AGENT_A" "$EXP_AGENT_B"; do
  ROOM="${AGENT_DM_ROOMS[$agent]}"
  ROOM_ENC=$(python3 -c "import urllib.parse, sys; print(urllib.parse.quote(sys.argv[1], safe=''))" "$ROOM")
  PROMPT=$(echo "$PROMPT_TEMPLATE" | sed -e "s/AGENT_PERSONA/$agent's persona/" -e "s/YOUR_HANDLE/$agent/g")
  TXN=$(date +%s%N)
  curl -s -X PUT "http://localhost:8008/_matrix/client/v3/rooms/$ROOM_ENC/send/m.room.message/$TXN" \
    -H "Authorization: Bearer $HUMAN_TOKEN" \
    -H "Content-Type: application/json" \
    -d "$(python3 -c "import json, sys; print(json.dumps({'msgtype':'m.text','body':sys.argv[1]}))" "$PROMPT")" >/dev/null
done
echo "negotiation prompts sent at $(date +%H:%M:%S)"
```

### 3c. Watch for stash + dispatch

The Mycelium plugin emits these log lines as the negotiation runs. Tail to confirm.

```bash
tail -F /tmp/openclaw/openclaw-$(date +%Y-%m-%d).log \
  | python3 -c "
import sys, re, json
PATTERNS = re.compile(r'return-address|notify-home|🎯|🤝|📬', re.I)
for raw in sys.stdin:
    raw = raw.strip()
    if not raw: continue
    try:
        d = json.loads(raw)
        msg = ' '.join(str(d.get(k,'')) for k in ('0','1','2'))
        ts = d.get('time','')[11:19]
    except Exception:
        continue
    if PATTERNS.search(msg):
        out = re.sub(r'\\{\\\"(?:module|subsystem)\\\":\\\"[^\\\"]+\\\"\\}', '', msg).strip().strip(',').strip()
        print(f'{ts} {out[:240]}', flush=True)
"
# Expected sequence (Ctrl-C to break):
#   return-address stashed: $EXP_AGENT_A → matrix:room:!XXX:server
#   return-address stashed: $EXP_AGENT_B → matrix:room:!YYY:server
#   🎯 → $EXP_AGENT_A     (round 1 tick)
#   🎯 → $EXP_AGENT_B
#   ... rounds repeat ...
#   🤝 → $EXP_AGENT_A     (consensus or timeout)
#   🤝 → $EXP_AGENT_B
#   📬 notify-home for [$EXP_AGENT_A, $EXP_AGENT_B] in $EXP_ROOM:session:<id>
#   notify-home → $EXP_AGENT_A on matrix:room:!XXX:server
#   notify-home → $EXP_AGENT_B on matrix:room:!YYY:server
```

## Phase 4: Verify the ship gate

The single assertion that says "this works": the consensus summary lands as a new Matrix message in each agent's DM with the human.

```bash
PASS=0; FAIL=0
for agent in "$EXP_AGENT_A" "$EXP_AGENT_B"; do
  ROOM="${AGENT_DM_ROOMS[$agent]}"
  ROOM_ENC=$(python3 -c "import urllib.parse, sys; print(urllib.parse.quote(sys.argv[1], safe=''))" "$ROOM")
  curl -s "http://localhost:8008/_matrix/client/v3/rooms/$ROOM_ENC/messages?dir=b&limit=10" \
    -H "Authorization: Bearer $HUMAN_TOKEN" > /tmp/_matrix_$agent.json
  GOT=$(python3 -c "
import json
d = json.loads(open('/tmp/_matrix_$agent.json').read(), strict=False)
for ev in d.get('chunk', []):
    if ev.get('type') == 'm.room.message' and ev.get('sender') == '@$agent:$SYNAPSE_SERVER':
        body = ev.get('content',{}).get('body','') or ''
        if 'Mycelium return trip' in body:
            print('YES')
            break
")
  if [ "$GOT" = "YES" ]; then
    echo "✓ $agent — return-trip message landed"
    PASS=$((PASS+1))
  else
    echo "✗ $agent — NO return-trip message in DM"
    FAIL=$((FAIL+1))
  fi
done
echo "result: pass=$PASS fail=$FAIL"
[ "$FAIL" -eq 0 ]
```

If `FAIL > 0`, check Phase 3c log output for missing stash / notify-home events. Common causes:

- Agent never received its first tick (didn't actually join the session). Check the agent's Matrix DM for replies — they may have errored out at `session join`.
- Stash didn't capture (`sessions.json` for that agent had no recent non-mycelium-room entry). Confirm with `cat ~/.openclaw/agents/$agent/sessions/sessions.json | python3 -m json.tool`.
- `runtime.channel.outbound.loadAdapter` returned no adapter. Should not happen on a working OpenClaw; if it does, OpenClaw's plugin SDK has shifted (this skill predates that version).
- Channel binding mismatch — `channels.mycelium-room.room` ≠ `$EXP_ROOM`. If you customized the room name, fix the binding.

## Phase 5: Capture artifacts (optional)

Useful for follow-up review or filing as a regression artifact on a PR.

```bash
ARTIFACT_DIR="$HOME/.mycelium/rooms/$EXP_ROOM/_test-artifacts"
mkdir -p "$ARTIFACT_DIR"

# Mycelium room transcripts
curl -s "$MYCELIUM_API_URL/rooms/$EXP_ROOM/messages?limit=200" > "$ARTIFACT_DIR/parent-room.json"

# Session sub-room transcripts (there can be more than one if you re-ran)
curl -s "$MYCELIUM_API_URL/rooms" | python3 -c "
import sys, json
rs = json.load(sys.stdin)
for r in rs:
    if r['name'].startswith('$EXP_ROOM:session:'):
        print(r['name'])
" | while read SR; do
  SAFE=$(echo "$SR" | tr ':' '_')
  curl -s "$MYCELIUM_API_URL/rooms/$SR/messages?limit=200" > "$ARTIFACT_DIR/${SAFE}.json"
done

# Both Matrix DMs
for agent in "$EXP_AGENT_A" "$EXP_AGENT_B"; do
  ROOM="${AGENT_DM_ROOMS[$agent]}"
  ROOM_ENC=$(python3 -c "import urllib.parse, sys; print(urllib.parse.quote(sys.argv[1], safe=''))" "$ROOM")
  curl -s "http://localhost:8008/_matrix/client/v3/rooms/$ROOM_ENC/messages?dir=b&limit=100" \
    -H "Authorization: Bearer $HUMAN_TOKEN" > "$ARTIFACT_DIR/dm-$agent.json"
done

# Gateway log slice (today only, filtered to plugin events)
grep -E '"subsystem":"plugins"|"module":"matrix' /tmp/openclaw/openclaw-$(date +%Y-%m-%d).log \
  > "$ARTIFACT_DIR/gateway.log" 2>/dev/null

echo "artifacts at $ARTIFACT_DIR"
```

## Phase 6: Cleanup

```bash
# Remove temp agents and channel bindings
python3 - <<PYEOF
import json, os
p = os.path.expanduser('~/.openclaw/openclaw.json')
cfg = json.load(open(p))
cfg['agents']['list'] = [a for a in cfg.get('agents', {}).get('list', [])
                        if not a.get('id', '').startswith('$EXP_ID')]
# Drop the matrix accounts
matrix_accounts = cfg.get('channels', {}).get('matrix', {}).get('accounts', {})
for k in list(matrix_accounts.keys()):
    if k.startswith('$EXP_ID'):
        matrix_accounts.pop(k, None)
# Drop bindings
cfg['bindings'] = [b for b in cfg.get('bindings', []) if not b.get('agentId','').startswith('$EXP_ID')]
# Optionally drop the mycelium-room channel binding if it points at our test room
mr = cfg.get('channels', {}).get('mycelium-room')
if mr and mr.get('room') == '$EXP_ROOM':
    cfg['channels'].pop('mycelium-room', None)
json.dump(cfg, open(p, 'w'), indent=2)
print('config cleaned')
PYEOF

# Workspaces + agent dirs
rm -rf ~/.openclaw/workspaces/${EXP_ID}-*
rm -rf ~/.openclaw/agents/${EXP_ID}-*

# Mycelium room (data persists on disk under ~/.mycelium/rooms; backend has it too)
curl -s -X DELETE "$MYCELIUM_API_URL/rooms/$EXP_ROOM" >/dev/null

# Restart gateway to drop the matrix sessions cleanly
openclaw gateway restart

# Note: Synapse has no public deactivation API by default. The throwaway users
# stay registered. Either deactivate via admin API (if you have a token) or
# accept the residue — the next ${EXP_ID}- prefix avoids collisions.
```

## Variant: negotiate in an unbound room

Confirms the channel plugin's room-agnostic routing: agents negotiate in a room name that the channel was never told about. Should still work end-to-end.

Modify Phase 1g so `channels.mycelium-room.room` is set to something *other* than `$EXP_ROOM`:

```bash
python3 - <<PYEOF
import json, os
p = os.path.expanduser('~/.openclaw/openclaw.json')
cfg = json.load(open(p))
cfg['channels']['mycelium-room']['room'] = 'totally-unrelated'   # NOT $EXP_ROOM
json.dump(cfg, open(p, 'w'), indent=2)
PYEOF
```

Run Phase 3 normally. Expected outcome: ticks dispatch as usual (`🎯 → ...`), consensus fires (`🤝 → ...`), notify-home delivers (`📬 ...`), and the return-trip Matrix message lands. Phase 4 passes. If the variant fails, the room-agnostic routing has regressed — the plugin is filtering session sub-rooms by parent room name again.

## Input

Describe the scenario however you want. Extract:

- **Scenario**: What are the agents deciding?
- **Personas**: Two personas in genuine conflict (REST vs GraphQL is a known-good shape)
- **Success criteria**: What does a good outcome look like?

For batch runs, provide a JSON file with the same `experiments[]` schema as the standard `before-and-after` skill.

## Flags

- `--phase=<0|0a|1|2|3|4|5|6>` — Run a single phase (e.g. `--phase=4` to re-verify ship gate against an already-running negotiation)
- `--scenario-only` — Skip Synapse user creation and OpenClaw config; assume Phase 1 has been done and reuse `$EXP_ID` from a prior run
- `--cleanup-only` — Skip everything; just run Phase 6
- `--unbound-room` — Run the variant from above (negotiate in a room the channel was never told about; verifies room-agnostic routing)
- No flags — full run: 0 → 1 → 2 → 3 → 4 → 5 → 6

## Troubleshooting

| Problem | Likely cause | Fix |
|---------|-------------|-----|
| Matrix `account ... stopped, error:Blocked hostname` | SSRF guard blocking `localhost` | Add `allowPrivateNetwork: true` to matrix account (Phase 1e) |
| Agent never joins matrix DM | `autoJoin` not set | Add `autoJoin: "always"` to matrix account |
| Agent reply is "OpenClaw: access not configured / Pairing code: …" | Pairing not approved | `openclaw pairing approve matrix <CODE>` (Phase 2 auto-handles) |
| Agent says "mycelium CLI isn't installed" but sandbox is off | `tools.exec.host` left at default `sandbox` | Set `tools.exec.host = "gateway"` and `security = "full"` (Phase 1d) |
| Agent says "I need /approve for exec" mid-negotiation | `tools.exec.security` is `"deny"` or `"allowlist"` without the right binary listed | `security = "full"` for test agents, or add binary to allowlist (Phase 1d) |
| Matrix DMs land but agent responds out of character | Account binding missing | `openclaw agents bind --agent X --bind matrix:X` (Phase 1f) |
| Negotiation runs but no return-trip message lands in DM | Stash not captured (no `return-address stashed: …` log line) | Check sessions.json freshness for the agent before negotiation; reprime DMs |
| `coordination_consensus` fires but Phase 4 still fails | `📬 notify-home` action not emitted by `routeConsensus` | Check `msg.room_name` in plugin log; usually means a stale plugin install (`mycelium adapter add openclaw --reinstall -y`) |
| Matrix register returns 400 | Username already exists from prior run | Use a fresh `$EXP_ID` prefix |

## Tips

- **Use Haiku.** This skill fires 10–40+ LLM calls per negotiation; cost adds up fast on Sonnet.
- **Strong opening positions matter.** The Mycelium-channel session is fresh — it has only SOUL.md and the `-m "..."` seed. Specific stake + concession + hard limit beats vague preference.
- **Reset between runs by killing the gateway and the agents.** The in-memory return-address stash dies with the gateway, which is a feature for tests (no zombie state).
- **Check the gateway log first** when something goes wrong. `/tmp/openclaw/openclaw-$(date +%Y-%m-%d).log` filtered for `[mycelium-room]` entries tells you exactly what the plugin saw and decided.
- **The Phase 2 pairing dance is the most fragile part of this skill.** If you find yourself running the skill repeatedly during dev, consider extracting Phase 2 to a script that lives outside the skill so you don't reset pairing state every run.
