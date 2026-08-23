# Backend tests

Unit tests run against local files + temp dirs — **no SLIM node, no Pi binary, no
live LLM, no backend server.** `conftest.py` isolates every test (a temp
`MYCELIUM_DATA_DIR`, a reset in-memory `in_memory_store`); `fakes.py` gives you the
fake coordination stack.

## Test a feature without a live stack

Import the fakes you need from `tests.fakes` and wire them into the service under
test. There is exactly one of each fake — don't re-declare them per file.

| You're testing… | Import | It stands in for |
| --- | --- | --- |
| The aligner / mediator driving a negotiation | `FakeChannel`, `FakePersister`, `FakeManaged`, `FakeManager` | the SLIM channel + persister + `RoomChannelManager` |
| The mediator's LLM decisions | `make_fake_llm` / `fake_llm_session_factory` | the Pi llm_session (`AlignerEngine`'s `llm_session_factory` seam) |
| `room_channels` provisioning / membership | `FakeSlimClient`, `FakeSession` | `slim_client.SlimClient` (the `slim_bindings` transport) |
| `PiSession.__call__` without spawning `pi` | `patch_pi_run(monkeypatch, stdout=…)` | `subprocess.run` / `shutil.which` |

### Example — drive the SAO mediator to agreement, node-free

```python
from tests.fakes import FakeChannel, FakePersister, FakeManaged, FakeManager, fake_llm_session_factory

persister = FakePersister()
channel = FakeChannel(persister, reply_conf=0.9)   # every prompt draws a reply
managed = FakeManaged("room", "mycelium", channel, persister)
manager = FakeManager(managed, ["growth", "risk", "aligner"])

engine = aligner.AlignerEngine(manager, handle="aligner", llm_session_factory=fake_llm_session_factory)
verdict = await engine.mediate("room")   # converges without a node or an LLM
```

### Example — provision a room channel against a fake node

```python
from app.services import room_channels
from tests.fakes import FakeSlimClient

monkeypatch.setattr(room_channels, "SlimClient", FakeSlimClient)
monkeypatch.setattr(room_channels, "node_reachable", lambda _e: True)
monkeypatch.setattr(room_channels, "to_channel_name", lambda *a: object())
monkeypatch.setattr(room_channels, "to_slim_name", lambda *a: object())
```

## Live-node / live-LLM slices

The SLIM roundtrip slices need a reachable node and **skip** without one — set
`MYCELIUM_SLIM_ENDPOINT`. Live-LLM tests are guarded by `MYCELIUM_LLM_TESTS=1`.

## Commands

```bash
uv run pytest tests/ -x -q
uv run ruff check . && uv run ruff format . && uv run ty check .
```
