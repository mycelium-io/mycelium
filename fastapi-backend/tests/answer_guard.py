# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""No route's response model drops a key its handler returned.

A response model filters what a route sends to the fields it declares. One
that was right the day it was written goes quietly wrong when the handler
grows a key, and whoever reads that key (the app, the CLI) stops seeing it
with no error anywhere. So every test that reaches a route checks it, whether
it goes over HTTP or calls the handler as a function:

- over HTTP, FastAPI's own serializer is wrapped: it's handed both what the
  handler returned and the model, and says which handler it serves;
- called directly, each modelled route's handler is wrapped where its module
  defines it.

Either way, what the handler returned is compared with what the model sends,
and a key the model drops fails the test that reached it. Only keys the
handler built as plain data are checked: a pydantic model it returned already
is the declared shape.
"""

from __future__ import annotations

import functools
import inspect
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import routing
from fastapi.routing import APIRoute
from pydantic import BaseModel, TypeAdapter

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    import pytest
    from fastapi import FastAPI

#: Handlers whose route model leaves a key out on purpose, as
#: ``"<file>:<function>"``: each with why.
DROPS_ON_PURPOSE: dict[str, str] = {
    "sessions.py:list_wakes": (
        "each wake-log record carries its room, and every record here is the path's room"
    ),
}


def dropped(raw: Any, sent: Any, at: str = "") -> Iterator[str]:
    """Each path in ``raw`` (plain data a handler built) missing from ``sent``."""
    if isinstance(raw, BaseModel):
        return
    if isinstance(raw, dict) and isinstance(sent, dict):
        for key, value in raw.items():
            here = f"{at}.{key}" if at else str(key)
            if key not in sent:
                yield here
            else:
                yield from dropped(value, sent[key], here)
    elif isinstance(raw, list | tuple) and isinstance(sent, list):
        for i, (item, out) in enumerate(zip(raw, sent, strict=False)):
            yield from dropped(item, out, f"{at}[{i}]")


def _check(handler: str, raw: Any, sent: Any) -> None:
    if handler in DROPS_ON_PURPOSE or isinstance(raw, BaseModel):
        return
    if keys := list(dropped(raw, sent)):
        raise AssertionError(
            f"{handler}'s response model drops {', '.join(keys)}, which it returns. Declare "
            "them on the model, or list the handler in DROPS_ON_PURPOSE with why."
        )


def _name(file: str | None, function: str | None) -> str:
    return f"{Path(file or '?').name}:{function or '?'}"


def _serialized(route: APIRoute, raw: Any) -> Any:
    """What ``route`` sends for ``raw``, the way FastAPI serializes it."""
    adapter = TypeAdapter(route.response_model)
    return adapter.dump_python(
        adapter.validate_python(raw),
        mode="json",
        by_alias=route.response_model_by_alias,
        exclude_unset=route.response_model_exclude_unset,
        exclude_none=route.response_model_exclude_none,
    )


def _guarded(route: APIRoute, endpoint: Callable[..., Any]) -> Callable[..., Any]:
    handler = _name(inspect.getsourcefile(endpoint), getattr(endpoint, "__name__", None))

    def check(raw: Any) -> None:
        if isinstance(raw, dict | list):
            try:
                sent = _serialized(route, raw)
            except Exception:
                return
            _check(handler, raw, sent)

    if inspect.iscoroutinefunction(endpoint):

        @functools.wraps(endpoint)
        async def run_async(*args: Any, **kwargs: Any) -> Any:
            raw = await endpoint(*args, **kwargs)
            check(raw)
            return raw

        return run_async

    @functools.wraps(endpoint)
    def run(*args: Any, **kwargs: Any) -> Any:
        raw = endpoint(*args, **kwargs)
        check(raw)
        return raw

    return run


def routes_of(routes: list[Any]) -> Iterator[APIRoute]:
    """Every API route, including those inside an included router (which
    FastAPI keeps behind a wrapper of its own rather than copying out)."""
    for route in routes:
        included = getattr(route, "original_router", None)
        if included is not None:
            yield from routes_of(included.routes)
        elif isinstance(route, APIRoute):
            yield route


def install(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    """Guard every route in ``app`` with a response model, for one test."""
    real = routing.serialize_response

    async def serialize(**kwargs: Any) -> Any:
        sent = await real(**kwargs)
        if kwargs.get("field") is None:
            return sent
        where = kwargs.get("endpoint_ctx") or {}
        # Serialized straight to JSON bytes when FastAPI can; read them back.
        shown = json.loads(sent) if isinstance(sent, bytes | str) else sent
        _check(_name(where.get("file"), where.get("function")), kwargs["response_content"], shown)
        return sent

    monkeypatch.setattr(routing, "serialize_response", serialize)
    for route in routes_of(app.routes):
        if route.response_model is None:
            continue
        endpoint = route.endpoint
        name = getattr(endpoint, "__name__", "")
        module = sys.modules.get(getattr(endpoint, "__module__", ""))
        if module is not None and getattr(module, name, None) is endpoint:
            monkeypatch.setattr(module, name, _guarded(route, endpoint))
