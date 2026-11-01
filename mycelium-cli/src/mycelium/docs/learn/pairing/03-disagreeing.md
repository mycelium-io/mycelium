# When you disagree

Sometimes the two agents or the two of you can't settle an approach. Each side
has a real reason and neither moves. Bring in the conductor, an engine the hub
runs, and its `concord` flow. Add the conductor once in the room's chat:

```text
/engine conductor
```

Then, in the task's thread, choose **Settle** under **+** and pick `web` and
`api`. Or ask it directly:

> @conductor concord: where should carts live?

Each side rates two reference outcomes, proposes one option and says why, then
rates both options with a reason. The one least happy with the best option
proposes something new that answers the other's objection, until both meet the
bar or the best option found stands.

The decision is saved under `context/decision/`, named after the task, with
who is short of the bar and why. Later work in the task is shown it, so neither
agent argues it again next week. Read it from a terminal:

```bash
mycelium memory get context/decision/keep-a-customers-cart-when-they-switch-devices
```
