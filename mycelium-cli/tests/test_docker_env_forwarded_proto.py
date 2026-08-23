# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``runtime.trusted_proxies`` → ``FORWARDED_ALLOW_IPS`` (#799).

uvicorn rewrites a request's scheme from ``X-Forwarded-Proto`` only when the
forwarder is one it trusts, and out of the box it trusts loopback alone. Behind
a TLS-terminating proxy the hop arrives from the Docker bridge, so the backend
keeps the ``http`` scheme it sees and hands out ``http://`` absolute URLs on an
``https://`` deployment.

Both halves are the contract: the key has to arrive when an operator sets it,
and it has to stay *absent* when they don't, because an empty value means "trust
no forwarder" rather than uvicorn's loopback default.
"""

from __future__ import annotations

from mycelium.config import MyceliumConfig
from mycelium.docker_utils import generate_env_file


def _parse_env(blob: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in blob.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def test_default_config_leaves_forwarded_headers_untrusted() -> None:
    """No proxy configured renders no key, so uvicorn keeps its loopback-only
    default and a direct caller cannot spoof the scheme."""
    assert "FORWARDED_ALLOW_IPS" not in _parse_env(generate_env_file(MyceliumConfig()))


def test_trusted_proxies_renders_forwarded_allow_ips() -> None:
    cfg = MyceliumConfig()
    cfg.runtime.trusted_proxies = "*"
    assert _parse_env(generate_env_file(cfg))["FORWARDED_ALLOW_IPS"] == "*"


def test_a_proxy_list_travels_verbatim() -> None:
    cfg = MyceliumConfig()
    cfg.runtime.trusted_proxies = "172.18.0.1,10.0.0.5"
    assert _parse_env(generate_env_file(cfg))["FORWARDED_ALLOW_IPS"] == "172.18.0.1,10.0.0.5"
