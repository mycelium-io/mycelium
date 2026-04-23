# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cisco Systems, Inc. and its affiliates

"""
HTTP client for Mycelium API.

Provides a simple wrapper around httpx with automatic configuration loading,
authentication, retry logic, and error handling.
"""

import time
from collections.abc import Callable
from typing import Any, TypeVar

import httpx

from mycelium.config import MyceliumConfig

T = TypeVar("T")


class MyceliumHTTPClient:
    """HTTP client for interacting with the Mycelium backend API."""

    def __init__(
        self,
        config: MyceliumConfig | None = None,
        base_url: str | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        retry_backoff: float = 1.0,
    ) -> None:
        if config is None:
            config = MyceliumConfig.load()

        self.config = config
        self.base_url = (base_url or config.server.api_url).rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff

        self.client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            headers=self._get_headers(),
        )

    def _get_headers(self) -> dict[str, str]:
        """Get default headers."""
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _should_retry(self, exception: Exception) -> bool:
        """Determine if request should be retried."""
        if isinstance(exception, httpx.ConnectError | httpx.TimeoutException):
            return True
        if isinstance(exception, httpx.HTTPStatusError):
            status = exception.response.status_code
            return status >= 500 or status == 429
        return False

    def _retry_request(self, request_func: Callable[[], httpx.Response]) -> httpx.Response:
        """Execute request with exponential backoff retry logic."""
        last_exception: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                response = request_func()
                response.raise_for_status()
                return response
            except Exception as e:
                last_exception = e
                if attempt < self.max_retries and self._should_retry(e):
                    backoff_time = self.retry_backoff * (2**attempt)
                    time.sleep(backoff_time)
                    continue
                raise

        if last_exception:
            raise last_exception
        raise RuntimeError("Retry logic failed unexpectedly")

    def get(self, path: str, params: dict[str, Any] | None = None, **kwargs: Any) -> httpx.Response:
        url = self._build_url(path)
        return self._retry_request(lambda: self.client.get(url, params=params, **kwargs))

    def post(
        self,
        path: str,
        json: dict[str, Any] | None = None,
        data: Any | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        url = self._build_url(path)
        return self._retry_request(lambda: self.client.post(url, json=json, data=data, **kwargs))

    def put(self, path: str, json: dict[str, Any] | None = None, **kwargs: Any) -> httpx.Response:
        url = self._build_url(path)
        return self._retry_request(lambda: self.client.put(url, json=json, **kwargs))

    def patch(self, path: str, json: dict[str, Any] | None = None, **kwargs: Any) -> httpx.Response:
        url = self._build_url(path)
        return self._retry_request(lambda: self.client.patch(url, json=json, **kwargs))

    def delete(self, path: str, **kwargs: Any) -> httpx.Response:
        url = self._build_url(path)
        return self._retry_request(lambda: self.client.delete(url, **kwargs))

    def _build_url(self, path: str) -> str:
        if not path.startswith("/"):
            path = f"/{path}"
        return path

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "MyceliumHTTPClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


def get_client(config: MyceliumConfig | None = None) -> MyceliumHTTPClient:
    """Get a configured HTTP client."""
    return MyceliumHTTPClient(config=config)
