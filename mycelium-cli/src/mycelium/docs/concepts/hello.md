# Hello

Hello replies to whatever you send it, and that's all it does. It doesn't
write memories, start negotiations or change the board. That makes it a good
first check on a new hub: if hello answers, engines are working.

```bash
mycelium engine create hello --kind hello --room sprint-plan
mycelium engine invoke hello "say hello and name the model you are" -r sprint-plan
```

## If it doesn't answer

A reply means the hub can reach your model and post messages back to the room.

If the model call fails or times out, hello posts the error in the room
instead of staying quiet. So if you see nothing at all, the message probably
never reached it. Check that the engine is registered in the room you're
talking in (`mycelium engine ls`), then look at the backend logs.

## It doesn't remember

Each message is answered on its own. Hello won't remember what you asked it
before. If you want something that keeps a conversation going, use a
[persona](#persona).
