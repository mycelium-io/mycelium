# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The CLI↔hub route contract.

The typed client is generated from ``openapi.json``, so its calls can't name a
route the hub doesn't serve. Every other hub call (``hub_client``, bare
``httpx``, ``MyceliumHTTPClient``) writes its path as a string, and a renamed
or deleted route fails at runtime, in front of someone, often quietly where
the caller fails soft.

This closes that seam against the committed ``openapi.json``, the same check
``mycelium-frontend/src/lib/api-contract.test.ts`` makes for the UI. It reads
the CLI's source rather than running it:

- a path passed straight to ``.get`` / ``.post`` / ``.request(...)`` / … is
  checked with its method;
- any other string that starts with ``/api/`` (a path built into a variable
  and passed on) is checked for its path alone.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SRC = _REPO / "mycelium-cli" / "src" / "mycelium"
_OPENAPI = _REPO / "openapi.json"

#: A used segment whose value is only known at runtime: ``{room}``.
_PARAM = "{}"

#: Backend params declared with FastAPI's ``:path`` converter, which swallow
#: slashes: a memory key is namespaced by design (``agents/x/notes``).
_SLASHY_PARAMS = {"{key}"}

#: At the app's address only ``/api/*`` reaches the hub, which serves its
#: health check there as well as at ``/health`` (the frontend's proxy alias).
_ALIASES = {"/api/health": "/health"}

_VERBS = {"get", "post", "put", "patch", "delete", "head"}
_METHOD_FIRST = {"request", "stream"}

#: Paths handed to a verb that don't go to the hub, as ``(module, path)``, each
#: with a comment saying where they do go. Empty today.
_NOT_THE_HUB: set[tuple[str, str]] = set()


@dataclass(frozen=True)
class Use:
    path: str
    method: str | None
    where: str

    def __str__(self) -> str:
        return f"{self.method or '*'} {self.path} ({self.where})"


def _text(node: ast.AST) -> str | None:
    """A string literal, with each f-string interpolation as ``{}``."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(str(v.value) if isinstance(v, ast.Constant) else _PARAM for v in node.values)
    return None


#: An interpolated base URL or a literal origin, then the hub path.
_HUB_PATH = re.compile(r"^(?:\{\}|https?://[^/]*)?(/[^\s]*)$")


def _hub_path(text: str, *, called: bool) -> str | None:
    """The hub path in ``text``, or None when it isn't one.

    A string handed straight to a verb counts when it is a path (``/rooms/x``
    against the hub's base URL is exactly the mistake to catch). Anywhere else
    only ``/api/...`` and ``/health`` count, since a path-shaped string is
    often a file path or prose.
    """
    m = _HUB_PATH.match(text)
    if m is None:
        return None
    path = m.group(1).split("?")[0].split("#")[0]
    if called or path.startswith("/api/") or path == "/health":
        return path
    return None


def _docstrings(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                ids.add(id(body[0].value))
    return ids


def _uses() -> list[Use]:
    """Every hub path the CLI's source names, with its method where it's called."""
    found: list[Use] = []
    for file in sorted(_SRC.rglob("*.py")):
        module = file.relative_to(_SRC).as_posix()
        tree = ast.parse(file.read_text(), filename=str(file))
        skip = _docstrings(tree)
        called: set[int] = set()
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            verb = node.func.attr
            if verb in _VERBS and node.args:
                method, arg = verb.upper(), node.args[0]
            elif verb in _METHOD_FIRST and len(node.args) >= 2:
                method, arg = _text(node.args[0]), node.args[1]
                method = method.upper() if method and method.isalpha() else None
            else:
                continue
            text = _text(arg)
            if text is None or (path := _hub_path(text, called=True)) is None:
                continue
            called.add(id(arg))
            if (module, path) not in _NOT_THE_HUB:
                found.append(Use(path, method, f"{module}:{node.lineno}"))
        # An f-string's literal parts are Constants of their own; only the whole counts.
        parts = {id(v) for n in ast.walk(tree) if isinstance(n, ast.JoinedStr) for v in n.values}
        seen = skip | called | parts
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant | ast.JoinedStr) or id(node) in seen:
                continue
            text = _text(node)
            if text is None or (path := _hub_path(text, called=False)) is None:
                continue
            if (module, path) not in _NOT_THE_HUB:
                found.append(Use(path, None, f"{module}:{node.lineno}"))
    return found


def _used_segments(path: str) -> list[str]:
    return [s for s in path.split("/") if s]


def _declared() -> dict[tuple[str, ...], set[str]]:
    spec = json.loads(_OPENAPI.read_text())
    return {
        tuple(s for s in path.split("/") if s): {m.upper() for m in ops}
        for path, ops in spec["paths"].items()
    }


def _is_param(segment: str) -> bool:
    return segment.startswith("{") and segment.endswith("}")


def _matches(used: list[str], declared: tuple[str, ...]) -> bool:
    """Whether a used path lines up with a declared one.

    A concrete value fills a declared param, and an interpolated value fills
    anything. A last segment that ends in an interpolation (``links{}``, where
    the tail is ``/backlinks`` or empty) may run on for any number of segments.
    Literal against literal is exact: that's what catches a renamed route.
    """
    open_tail = bool(used) and used[-1] != _PARAM and used[-1].endswith(_PARAM)
    if open_tail:
        head = used[-1].removesuffix(_PARAM)
        used = [*used[:-1], *([head] if head else [])]
    if declared and declared[-1] in _SLASHY_PARAMS and len(used) >= len(declared):
        used = used[: len(declared)]  # the key swallows the rest
    if open_tail and len(used) <= len(declared):
        declared = declared[: len(used)]  # the interpolated tail fills the rest
    if len(used) != len(declared):
        return False
    return all(_is_param(d) or u == _PARAM or d == u for u, d in zip(used, declared, strict=True))


def _served(use: Use, declared: dict[tuple[str, ...], set[str]]) -> bool:
    used = _used_segments(_ALIASES.get(use.path, use.path))
    return any(
        _matches(used, path) and (use.method is None or use.method in methods)
        for path, methods in declared.items()
    )


_USES = _uses()
_DECLARED = _declared()


def test_finds_the_call_surface_to_check() -> None:
    # Guards the scanner itself: moving every call behind a path builder would
    # quietly empty this suite rather than fail it.
    assert len(_USES) > 60
    assert sum(u.method is not None for u in _USES) > 50


@pytest.mark.parametrize("use", _USES, ids=str)
def test_hub_path_is_in_openapi(use: Use) -> None:
    assert _served(use, _DECLARED), (
        f"{use} matches no route in openapi.json. If the hub renamed it, follow it here; "
        "if it isn't a hub call, add it to _NOT_THE_HUB with why."
    )


@pytest.mark.parametrize(
    ("path", "method", "served"),
    [
        ("/api/rooms/{}/memory", "GET", True),
        ("/api/rooms/{}/memory/{}", "GET", True),
        ("/api/rooms/{}/memory/agents/{}/notes", "GET", True),
        ("/api/rooms/{}/links{}", "GET", True),
        ("/api/health", "GET", True),
        ("/rooms/{}/a2a/state", "GET", False),
        ("/api/rooms/{}/memroy", "GET", False),
        ("/api/rooms/{}/tasks", "DELETE", False),
    ],
)
def test_matching(path: str, method: str, served: bool) -> None:
    assert _served(Use(path, method, "here"), _DECLARED) is served
