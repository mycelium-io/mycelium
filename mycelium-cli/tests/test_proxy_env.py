# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``NO_PROXY`` with IPv6 in brackets no longer stops every command."""

from __future__ import annotations

import httpx
import pytest

from mycelium import proxy_env


@pytest.mark.parametrize(
    ("given", "read"),
    [
        ("localhost,[fd00::1],127.0.0.1", "localhost,fd00::1,127.0.0.1"),
        ("[::1]:8000", "::1"),
        ("fd00::/8,.internal", ".internal"),
        ("localhost, 10.0.0.0/8", "localhost,10.0.0.0/8"),
    ],
)
def test_no_proxy_is_rewritten_as_httpx_reads_it(given: str, read: str) -> None:
    assert proxy_env.readable(given)[0] == read


def test_a_repaired_no_proxy_builds_a_client_and_still_bypasses(monkeypatch) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://proxy:3128")
    monkeypatch.setenv("NO_PROXY", "localhost,[fd00::1]")
    monkeypatch.delenv("no_proxy", raising=False)
    with pytest.raises(httpx.InvalidURL):
        httpx.Client()
    proxy_env.repair()
    client = httpx.Client()
    direct = client._transport_for_url(httpx.URL("http://[fd00::1]:8000/health"))
    assert direct is client._transport


def test_an_ipv6_range_is_left_out_with_a_note(monkeypatch, capsys) -> None:
    monkeypatch.setenv("NO_PROXY", "fd00::/8,localhost")
    proxy_env.repair()
    assert capsys.readouterr().err.startswith("mycelium: ignoring fd00::/8 in NO_PROXY")
