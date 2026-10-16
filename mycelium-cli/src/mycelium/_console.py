# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A Windows console that prints what the CLI prints.

A Windows console starts on a legacy code page (cp1252 or cp437), so the first
``✓`` or ``→`` the CLI prints raises ``UnicodeEncodeError``, through Rich and
plain ``print`` alike, and ``PYTHONIOENCODING`` doesn't reach Rich's legacy
console writer. This switches the console itself to UTF-8 and turns on its
escape-code handling (so Rich draws with ANSI rather than its legacy writer),
and makes the streams UTF-8 with replacement as a last resort, before any
command module creates a Console. Nothing changes on macOS or Linux.
"""

from __future__ import annotations

import contextlib
import sys


def use_utf8_console() -> None:
    if sys.platform != "win32":
        return
    with contextlib.suppress(Exception):
        _console_utf8_and_vt()
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            with contextlib.suppress(Exception):
                reconfigure(encoding="utf-8", errors="replace")


def _console_utf8_and_vt() -> None:
    import ctypes  # noqa: PLC0415 - Windows only
    from ctypes import wintypes  # noqa: PLC0415

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # ty: ignore[unresolved-attribute]
    utf8 = 65001
    kernel32.SetConsoleOutputCP(utf8)
    kernel32.SetConsoleCP(utf8)
    kernel32.GetStdHandle.restype = wintypes.HANDLE
    enable_virtual_terminal_processing = 0x0004
    std_output_handle, std_error_handle = -11, -12
    for which in (std_output_handle, std_error_handle):
        handle = kernel32.GetStdHandle(which)
        mode = wintypes.DWORD()
        if handle and kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | enable_virtual_terminal_processing)
