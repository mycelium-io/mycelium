# Backend tests

Unit tests run against local files + temp dirs: **no Pi binary, no live LLM, no
backend server.** `conftest.py` isolates every test (a temp
`MYCELIUM_DATA_DIR`, a reset in-memory `in_memory_store`); `fakes.py` gives you a
fake room.

## Test a feature without a live stack

Import the fakes you need from `tests.fakes` and wire them into the service under
test. There is exactly one of each fake, so don't re-declare them per file.

| You're testing… | Import | It stands in for |
| --- | --- | --- |
| An engine posting into a room and asking its members | `FakePersister`, `FakeManaged`, `FakeManager` | the room's persister + `ManagedRoomChannel` + `RoomChannelManager` |
| `PiSession.__call__` without spawning `pi` | `patch_pi_run(monkeypatch, stdout=…)` | `subprocess.run` / `shutil.which` |

A room's real channel needs nothing either: `room_channels.manager.get(room)`
opens it for any room whose folder exists, over the room's transcript on disk.

### Example: put a turn to a member and get its answer

```python
from app.services import turns
from tests.fakes import FakeManaged, FakePersister

persister = FakePersister(reply_conf=0.9)   # every prompt draws a reply
managed = FakeManaged("room", persister)

prose = await turns.addressed_turn(managed, persister, sender="conductor", handle="growth", ...)
persister.texts()   # what the engine posted
```

`tests/test_turns.py` has the full call, and `tests/test_conductor.py` drives
whole flows with scripted replies (a listener on the persister).

## Live-LLM slices

Live-LLM tests are guarded by `MYCELIUM_LLM_TESTS=1`.

## Commands

```bash
uv run pytest tests/ -x -q
uv run ruff check . && uv run ruff format . && uv run ty check .
```
