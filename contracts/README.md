# contracts

Frozen JSON constants that more than one component has to reproduce
**independently**.

Each file exists for the same reason: the thin `uv tool` CLI cannot import the
backend, and the frontend can't import either, so a shared value ends up copied.
A copy that nothing checks is a copy that drifts — and these particular
divergences fail quietly (an MLS group-key mismatch means members simply can't
join; a message-type mismatch means the UI silently hides messages).

So each contract is read by the test suites on **both** sides, which assert
their own copy against it. Neither copy can change without turning a unit gate
red.

## Working with them

- Changing a shared value is a deliberate edit to the contract file **in the
  same PR** as the code change. Both suites then re-lock to the new value.
- Never edit one side's copy to make a red test pass — that's the drift the
  contract exists to catch.
- Each file's `_comment` names the modules bound by it and the tests that assert
  it. Keep that pointer current; it's the only thing telling the next reader
  where the other copy lives.
