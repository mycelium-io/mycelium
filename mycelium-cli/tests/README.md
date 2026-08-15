# CLI tests

Unit tests run **without a SLIM node, a running backend, or live HTTP.**
`conftest.py` holds the shared fakes + fixtures; import the classes from
`tests.conftest`, or take the fixtures by name (pytest injects them). There is
exactly one of each fake — don't re-declare them per file.

## Test a command / connector without a live stack

| You're testing… | Use | It stands in for |
| --- | --- | --- |
| A command that calls the backend (`room`, `memory`, `plan`, …) | the `backend` fixture + patch the one generated `…​.sync` | the typed `mycelium_backend_client` plumbing |
| Connector HTTP (`slim.member.announce_presence`, briefing fetch) | the `fake_httpx` fixture, `FakeResp` | `httpx.AsyncClient` / `httpx.Client` |
| Joining/publishing over SLIM (`slim.member.publish_once`, the `l9 send`/`slim send` plumbing) | `FakeSlimClient` (or the `fake_slim_client` fixture) | `slim.client.SlimClient` |
| Anything that touches `~/.mycelium` | the `isolated_home` fixture | points `Path.home()` at a temp dir |

### Example — a command test (typed backend client)

```python
from mycelium.commands import room as room_cmd

def test_list_rooms(backend, monkeypatch):
    backend(room_cmd, room="demo")          # stub config/_typed_client/_resolve_room
    monkeypatch.setattr(
        "mycelium_backend_client.api.rooms.list_rooms_api_rooms_get.sync",
        lambda **kw: RoomListResponse(rooms=[...]),
    )
    result = CliRunner().invoke(room_cmd.app, ["list"])
    assert result.exit_code == 0
```

### Example — a connector HTTP test (`fake_httpx`)

```python
from tests.conftest import FakeHTTPX, FakeResp

async def test_announce(fake_httpx: FakeHTTPX):
    await member.announce_presence("http://localhost:8000", "myroom", "agent-a")
    assert fake_httpx.calls == [("POST", ".../api/rooms/myroom/sessions", {"agent_handle": "agent-a"})]

    fake_httpx.respond_with(lambda *_: FakeResp(boom=True))   # exercise the error branch
```

### Example — joining + publishing over SLIM (`FakeSlimClient`)

```python
from tests.conftest import FakeSlimClient

monkeypatch.setattr(member, "SlimClient", fake_slim_client)   # the fixture, reset per test
await member.publish_once(
    api_url="http://localhost:8000", node_endpoint="http://127.0.0.1:46357",
    room="r", handle="agent-a", payload=l9.serialize(content),
)
assert FakeSlimClient.published == [l9.serialize(content)]
```

## Commands

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check . && uv run pytest tests/ -x -q
```
