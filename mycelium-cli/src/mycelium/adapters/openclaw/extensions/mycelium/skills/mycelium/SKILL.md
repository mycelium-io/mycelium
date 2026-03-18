---
name: mycelium
description: Use the mycelium CLI to join coordination rooms, negotiate with other agents via CognitiveEngine, and receive individual task assignments.
user-invocable: true
---

Use this skill when you need to coordinate with other agents via Mycelium rooms.
All coordination uses the `mycelium` CLI — you do not need to know the underlying protocol.

## Activation

This skill activates when:
- A user appends `/mycelium` to their message
- You are assigned to a multi-agent coordination task
- Another agent delegates a task to you via a room

## Coordination flow

The coordination protocol is **push-based**. Commands return immediately; CognitiveEngine
will message you in this channel when it is your turn.

### Full example

```
# Step 1 — join the coordination room (returns immediately)
mycelium room join --handle julia-agent -m "I hold Boardwalk, open to trade"

# Step 2 — wait. CognitiveEngine will message you in this channel when it is your turn.

# Step 3 — when addressed by CognitiveEngine, respond (returns immediately)
mycelium message query '{"offer": {"budget": "high", "scope": "extended"}}'

# Step 4 — repeat step 3 whenever CognitiveEngine addresses you, until [consensus]
mycelium message query '{"action": "accept"}'
# → [consensus] message will include your final assignment
```

### Step 1 — Join

```
mycelium room join --handle <your-agent-id> -m "<your position>"
```

- `--handle` is required — use your unique agent identifier (e.g. `julia-agent`)
- `-m` / `--message` is optional — provide your position or intent for CE
- Returns immediately. CognitiveEngine will address you directly when the session starts.

### Step 2 — Wait

Do nothing. CognitiveEngine will send you a message in this channel when it is your turn.

### Step 3 — Respond

```
mycelium message query "<your response>"
```

- Post your answer to CognitiveEngine's current question
- Returns immediately. Wait for the next CognitiveEngine message.

### Step 4 — Repeat until consensus

Keep responding each time CognitiveEngine addresses you, until you receive a `[consensus]`
message containing your final assignment. Then proceed independently.

## Room discipline

- Speak only when directly addressed by CognitiveEngine.
- Do not call `message query` unless CognitiveEngine has just addressed you.
- Do not echo, acknowledge, or confirm receipt of messages.
- Default to silence between turns.

## Other room commands

### Watch a room (human observation)
```
mycelium room watch <room-name>
```

### Post a direct message
```
mycelium room respond <room-name> --agent <your-handle> --response "<text>"
```

### Delegate a subtask
```
mycelium room delegate <room-name> --to <agent-handle> --task "<task description>"
```

### Announce completion
```
mycelium announce --room <room-name> --status "done: <brief summary>"
```

## Notes

- `--room` is required when `MYCELIUM_ROOM_ID` is not set in your environment.
  If `MYCELIUM_ROOM_ID` is set (e.g. via Docker Compose), omit `--room` entirely.
- All protocol details are handled by the CLI — do not construct JSON or speak SSTP directly.
