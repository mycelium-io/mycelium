# CLI tests

Unit tests run **without a running backend or live HTTP.**
`conftest.py` holds the shared fakes + fixtures; import the classes from
`tests.conftest`, or take the fixtures by name (pytest injects them). There is
exactly one of each fake — don't re-declare them per file.

No test reaches a real hub: an autouse guard in `conftest.py` fails every real
HTTP request, so a test that stubs the wrong layer fails rather than writing to
whatever hub answers on the developer's machine.

## Test a command / connector without a live stack

| You're testing… | Use | It stands in for |
| --- | --- | --- |
| A command that calls the hub | `install_stand_in_hub(monkeypatch)` (or the `stand_in_hub` fixture), answering each request with the hub's real shape (`memory_read(...)` fills a memory) | the hub, behind every client: the typed client and `hub_client` alike |
| One generated call in isolation | patch its `…​.sync_detailed` with `tests.hub_answers.ok(model)` / `refused(status)` | that one route |
| Anything that touches `~/.mycelium` | the `isolated_home` fixture | points `Path.home()` at a temp dir |

### Example — a command test (the stand-in hub)

```python
from tests.conftest import install_stand_in_hub, memory_read


def test_board_new_files_the_task(monkeypatch):
    hub = install_stand_in_hub(monkeypatch)
    # The typed client parses what comes back against openapi.json, so answer
    # with the hub's real shape and status (a task is a 201 MemoryRead).
    hub.answer = lambda request: (201, memory_read("work/x", "demo", episode="urn:…"))
    result = CliRunner().invoke(board_cmd.app, ["new", "Ship it"])
    assert result.exit_code == 0
    assert hub.sent("POST", "/api/rooms/demo/tasks")
```

## Commands

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check . && uv run pytest tests/ -x -q
```
