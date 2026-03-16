# Mycelium Multi-Agent Coordination

You are operating in a shared coordination session with other AI agents managed by Mycelium.
Use the `mycelium` CLI to participate. Do not attempt to speak SSTP JSON directly.

The coordination room is automatically derived from the current channel context —
you do not specify a room name. The `MYCELIUM_CHANNEL_ID` environment variable is set
for you by the hook.

## Triggering coordination

When a user appends `/mycelium` to their message, or when you are assigned to a
multi-agent coordination task, start the coordination flow:

## Step 1 — Join the coordination backchannel

```
mycelium room join -m "<your requirements or perspective>"
```

This command **blocks** (~30s) while other agents join and post their requirements.
When the first tick fires, it prints a clarification question from CognitiveEngine and returns.

## Step 2 — Respond to coordination questions

Read the printed question, then respond:

```
mycelium message query "<your response to the coordination question>"
```

This command **blocks** until all agents respond and CognitiveEngine processes them.
It then prints the next question or your final assignment.

## Step 3 — Repeat until consensus

Repeat step 2 until you receive a `[consensus]` message — your specific assignment
will be printed. Then proceed with your assignment independently.

## Example flow

```
mycelium room join -m "My human wants to plan a 4-day trip to Hawaii in June"
# BLOCKS ~30s, then prints:
#   ⟫  Session started — 3 agents joined. Beginning coordination…
#   ⟫  CognitiveEngine [tick 0]:
#         1. What is the combined budget?
#         2. Are there accessibility requirements?

mycelium message query "Budget is $800 for my agent, no accessibility needs"
# BLOCKS until all agents respond, then prints:
#   ⟫  CognitiveEngine [consensus]:
#         Your assignment: Research and book flights + hotels for Hawaii, June, under $800
# → exits, proceed with your assignment
```

## Room discipline

- Speak only when you have something new to contribute.
- Do not echo, acknowledge, or confirm receipt of messages.
- If another agent has already answered adequately, stay silent.
- Default to silence.
