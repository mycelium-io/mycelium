# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
LLM provider for semantic negotiation agents.

Replaces config/utils.get_llm_provider() from ioc-cfn-cognitive-agents.
Returns a Callable[[str], str] backed by LiteLLM using Mycelium's
settings.LLM_MODEL / LLM_API_KEY / LLM_BASE_URL.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


def get_llm_provider() -> Callable[[str], str]:
    """Return a prompt → response callable backed by LiteLLM."""

    def _call(prompt: str) -> str:
        import logging

        import litellm

        from app.config import settings

        kwargs: dict = {
            "model": settings.LLM_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": 8000,
        }
        if settings.LLM_API_KEY:
            kwargs["api_key"] = settings.LLM_API_KEY
        if settings.LLM_BASE_URL:
            kwargs["base_url"] = settings.LLM_BASE_URL

        try:
            resp = litellm.completion(**kwargs)
        except litellm.AuthenticationError:
            logging.getLogger(__name__).warning(
                "LLM authentication failed for model %s. Check LLM_API_KEY in ~/.mycelium/.env",
                settings.LLM_MODEL,
            )
            raise RuntimeError(
                f"LLM authentication failed for {settings.LLM_MODEL}. "
                "Check LLM_API_KEY in ~/.mycelium/.env"
            )
        return resp.choices[0].message.content or ""

    return _call
