# Write a task that splits well

The lead splits the task from what you wrote. A vague task gets a vague
split; a task that names its parts gets parts that fit together.

Too thin:

```
Add CSV export
```

Splits well:

```
Add CSV export for orders.
Parts: an /api/orders/export endpoint that streams CSV; an Export button on
the Orders page; tests for both, including an empty list and 10,000 rows.
Done when: a person can download this month's orders from the Orders page,
and the tests pass in CI.
Don't change the existing orders API.
```

What makes the second one work:

- **The parts are named**, and each could be handed to someone on its own.
- **Done is something anyone can check.**
- **The limits are said out loud**, so no member wanders into them.
