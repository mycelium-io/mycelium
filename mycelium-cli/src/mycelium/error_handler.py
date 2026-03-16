"""Error handler for formatting exceptions into user-friendly CLI messages."""

import httpx
import typer

from mycelium.exceptions import APIError, MyceliumError


def format_error(error: Exception, verbose: bool = False) -> str:
    """Format an exception into a user-friendly message."""
    if isinstance(error, MyceliumError):
        return _format_mycelium_error(error, verbose)
    if isinstance(error, httpx.HTTPStatusError):
        return _format_http_status_error(error, verbose)
    if isinstance(error, httpx.ConnectError):
        return _format_connect_error(error, verbose)
    if isinstance(error, httpx.TimeoutException):
        return _format_timeout_error(error, verbose)
    return _format_generic_error(error, verbose)


def _format_mycelium_error(error: MyceliumError, verbose: bool) -> str:
    lines = [f"Error: {error.message}"]
    if error.suggestion:
        lines.append(f"\nSuggestion: {error.suggestion}")
    if isinstance(error, APIError) and error.status_code:
        lines.append(f"Status Code: {error.status_code}")
    if verbose:
        lines.append(f"\nException Type: {type(error).__name__}")
        original_error = getattr(error, "original_error", None)
        if original_error:
            lines.append(f"Original Error: {original_error}")
    return "\n".join(lines)


def _format_http_status_error(error: httpx.HTTPStatusError, verbose: bool) -> str:
    lines = []
    status_code = error.response.status_code

    detail = None
    try:
        body = error.response.json()
        detail = body.get("detail") if isinstance(body, dict) else None
        if isinstance(detail, dict):
            detail = detail.get("message") or detail.get("error") or str(detail)
    except Exception:
        pass

    if detail:
        lines.append(f"Error: {detail}")
    else:
        lines.append(f"Error: HTTP {status_code} - {error.response.reason_phrase}")
        lines.append(f"URL: {error.request.url}")

    if not detail:
        if status_code == 401:
            lines.append("\nSuggestion: Authentication required.")
        elif status_code >= 500:
            lines.append("\nSuggestion: Server error. Try again later.")

    if verbose:
        lines.append(f"\nHTTP {status_code} — {error.request.url}")
        try:
            response_text = error.response.text
            if response_text:
                lines.append(f"Response Body: {response_text[:500]}")
        except Exception:
            pass

    return "\n".join(lines)


def _format_connect_error(error: httpx.ConnectError, verbose: bool) -> str:
    lines = [
        "Error: Failed to connect to the Mycelium API",
        "\nSuggestion: Check that the Mycelium backend is running with 'mycelium status'",
    ]
    if verbose:
        lines.append(f"\nOriginal Error: {error}")
    return "\n".join(lines)


def _format_timeout_error(error: httpx.TimeoutException, verbose: bool) -> str:
    lines = [
        "Error: Request timed out",
        "\nSuggestion: The server is taking too long to respond. Try again later.",
    ]
    if verbose:
        lines.append(f"\nOriginal Error: {error}")
    return "\n".join(lines)


def _format_generic_error(error: Exception, verbose: bool) -> str:
    lines = [f"Error: {str(error)}"]
    if verbose:
        lines.append(f"\nException Type: {type(error).__name__}")
    return "\n".join(lines)


def print_error(error: Exception | str, verbose: bool = False, exit_code: int = 1) -> None:
    """Print a formatted error message to stderr."""
    message = format_error(error, verbose) if isinstance(error, Exception) else str(error)
    typer.secho(message, fg=typer.colors.RED, err=True)
    if exit_code > 0:
        raise typer.Exit(code=exit_code)
