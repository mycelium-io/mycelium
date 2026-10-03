# When you disagree

Sometimes the two agents, or the two of you, can't settle an approach: each
side has a real reason and neither moves. Bring in the aligner, an engine the
hub runs for this. Add it once, in the room's chat:

```text
/engine aligner
```

Then ask it in the task's thread:

> @aligner help @web and @api agree on where carts live

It works out what each side actually needs, proposes something both can
accept, and asks each of them in turn. It stops as soon as they agree, or
says plainly that they didn't.

Keep the outcome as a decision, so neither agent argues it again next week.
In the chat:

```text
/memory decisions/cart-storage Carts live in Postgres for 30 days. A cart is written at most once every 5 seconds.
```

Or from a terminal:

```bash
mycelium memory set decisions/cart-storage "Carts live in Postgres for 30 days."
```
