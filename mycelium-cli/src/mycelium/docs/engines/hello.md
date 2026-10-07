# Hello

Hello replies to whatever you send it, and that's all it does. It doesn't write
memories, start negotiations or change the board. That makes it a good first
check on a new hub. If hello answers, engines are working.

```bash
mycelium engine create greeter --kind hello --room sprint-plan
mycelium engine invoke greeter "say hello and name the model you are" -r sprint-plan
```

## If it doesn't answer

A reply means the hub can reach your model and post messages back to the room.

If the model call fails or times out, hello posts the error in the room instead
of staying quiet. So if you see nothing at all, the message probably never
reached it. Work through these:

1. Check that the engine is in the room you're talking in with
   `mycelium engine ls -r sprint-plan`.
2. Check the model. `mycelium doctor` makes a real model call and says what's
   wrong. See [Models](#models).
3. Read the hub's logs. For a Docker hub, run `mycelium logs mycelium-backend`.
   For the Mac app, open `~/.mycelium/logs/desktop.log`.

Hello answers each message on its own and doesn't remember earlier ones.
