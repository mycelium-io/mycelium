# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Custom exceptions for Mycelium CLI."""


class MyceliumError(Exception):
    """Base exception for all Mycelium CLI errors."""

    def __init__(self, message: str, suggestion: str | None = None) -> None:
        self.message = message
        self.suggestion = suggestion
        super().__init__(message)


class ConfigError(MyceliumError):
    """Configuration-related errors."""

    pass


class ConfigValidationError(ConfigError):
    """Configuration validation failed."""

    def __init__(self, message: str, field: str | None = None) -> None:
        if field:
            full_message = f"Invalid configuration for '{field}': {message}"
        else:
            full_message = f"Invalid configuration: {message}"
        super().__init__(
            message=full_message,
            suggestion="Check your configuration file at ~/.mycelium/config.toml",
        )
        self.field = field


class APIError(MyceliumError):
    """API communication errors."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        suggestion: str | None = None,
    ) -> None:
        super().__init__(message, suggestion)
        self.status_code = status_code


class APIConnectionError(APIError):
    """Backend is not reachable."""

    def __init__(self, base_url: str, original_error: Exception | None = None) -> None:
        super().__init__(
            message=f"Failed to connect to Mycelium API at {base_url}",
            suggestion="Check that the Mycelium backend is running with 'mycelium status'",
        )
        self.base_url = base_url
        self.original_error = original_error


class NetworkError(MyceliumError):
    """Network-related errors."""

    pass
