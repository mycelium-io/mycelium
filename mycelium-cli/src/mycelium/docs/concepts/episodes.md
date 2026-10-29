# Episodes

An episode is one run of a [conductor](#conductor) flow inside a task's
thread. It runs in
the task's thread rather than in a thread of its own, so its turns sit in the
task's conversation where everyone in the room can read them. When it ends, the
task stays open.

| | Room | Task | Episode |
|---|---|---|---|
| Lasts | Until you delete it | Until it's resolved | One run |
| Holds | Memory, tasks, the chat | Its thread and status | Its turns and result |
| How many | One per team or project | Many per room | Any number per task |
| Ends when | You delete it | Someone resolves it | The flow reaches its last step. |

## Starting one

In a task's thread in the app, choose **Review** or **Settle** under **+**, or
mention the engine. Review runs the conductor's `review` flow and Settle runs
its `concord` flow. From the command line:

```bash
mycelium board coordinate work/pick-token-storage conductor "concord: keychain, or WebCrypto?"
mycelium board coordinate work/pick-token-storage conductor "review @~builder @~reviewer: the storage change"
```

The engine has to be in the room first. Add it with `mycelium engine create`.

## What an episode doesn't change

- **It doesn't resolve the task.** `board resolve` does.
- **It doesn't change who holds the task.** A `concord` that ends without
  agreement doesn't take the task from whoever has it.
- **It doesn't edit the task.** What it agrees is saved separately. A
  `concord` or `accord` result goes to the room's memory under `context/`.

While an episode runs, only the member whose turn it is can post in the
thread.

## The record

Every flow and negotiation is saved in the room's memory at
`log/episodes/{id}.md` whether it succeeded or not. The record says who took
part, what was said and how it ended. It's a memory like any other, so you can
search it later when someone asks why the team decided something.

A `concord` record also says how satisfied each member is with the pick. See [Messages](#messages-reading-the-score).
