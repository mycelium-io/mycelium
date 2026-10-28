# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""No route's response model drops a key its handler returned.

A response model filters what a route sends to the fields it declares. One
that was right the day it was written goes quietly wrong when the handler
grows a key, and whoever reads that key (the app, the CLI) stops seeing it
with no error anywhere. So every test that reaches a route checks it, whether
it goes over HTTP or calls the handler as a function:

- over HTTP, the handler FastAPI calls for the route (``dependant.call``) is
  wrapped;
- called directly, the same handler is wrapped where its module defines it.

Either way, what the handler returned is compared with what the model sends,
and a key the model drops fails the test that reached it. Only keys the
handler built as plain data are checked: a pydantic model it returned already
is the declared shape.
"""

from __future__ import annotations

import functools
import inspect
import sys
from typing import TYPE_CHECKING, Any

from fastapi.routing import APIRoute
from pydantic import BaseModel, TypeAdapter

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    import pytest
    from fastapi import FastAPI

#: Routes whose model leaves a key out on purpose, as ``(method, path)`` with
#: the path as its router declares it: each with why.
DROPS_ON_PURPOSE: dict[tuple[str, str], str] = {
    ("GET", "/rooms/{room_name}/sessions/wakes"): (
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


def _fail(route: str, keys: list[str]) -> None:
    raise AssertionError(
        f"{route}'s response model drops {', '.join(keys)}, which its handler returns. "
        "Declare them on the model, or list the route in DROPS_ON_PURPOSE with why."
    )


def _serialized(route: APIRoute, raw: Any) -> Any:
    """What ``route`` sends for ``raw``, the way FastAPI serializes it."""
    adapter = TypeAdapter(route.response_model)
    model = adapter.validate_python(raw)
    return adapter.dump_python(
        model,
        mode="json",
        by_alias=route.response_model_by_alias,
        exclude_unset=route.response_model_exclude_unset,
        exclude_none=route.response_model_exclude_none,
    )


def _check(route: APIRoute, raw: Any) -> None:
    methods = sorted(route.methods or ())
    if any((method, route.path) in DROPS_ON_PURPOSE for method in methods):
        return
    if isinstance(raw, BaseModel) or not isinstance(raw, dict | list):
        return
    try:
        sent = _serialized(route, raw)
    except Exception:
        return
    if keys := list(dropped(raw, sent)):
        _fail(f"{'/'.join(methods)} {route.path}", keys)


def _guarded(route: APIRoute, endpoint: Callable[..., Any]) -> Callable[..., Any]:
    if inspect.iscoroutinefunction(endpoint):

        @functools.wraps(endpoint)
        async def run_async(*args: Any, **kwargs: Any) -> Any:
            raw = await endpoint(*args, **kwargs)
            _check(route, raw)
            return raw

        return run_async

    @functools.wraps(endpoint)
    def run(*args: Any, **kwargs: Any) -> Any:
        raw = endpoint(*args, **kwargs)
        _check(route, raw)
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
    """Guard every route in ``app`` with a response model, for one test: where
    FastAPI calls its handler (``dependant.call``), and where its module
    defines it, for a test that calls the handler itself."""
    for route in routes_of(app.routes):
        if route.response_model is None:
            continue
        endpoint = route.endpoint
        guarded = _guarded(route, endpoint)
        monkeypatch.setattr(route.dependant, "call", guarded)
        name = getattr(endpoint, "__name__", "")
        module = sys.modules.get(getattr(endpoint, "__module__", ""))
        if module is not None and getattr(module, name, None) is endpoint:
            monkeypatch.setattr(module, name, guarded)
