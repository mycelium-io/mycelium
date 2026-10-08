# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Whether a process is still running, on every platform."""

from __future__ import annotations

import os
import sys


def pid_alive(pid: int) -> bool:
    """Whether a process with this id is running.

    ``os.kill(pid, 0)`` asks that on macOS and Linux. On Windows it doesn't:
    signal 0 there is a Ctrl+C sent to the process's console group, which
    interrupts it when it leads one and raises WinError 87 when it doesn't. So
    Windows opens the process and reads whether it has exited.
    """
    if pid <= 0:
        return False
    if sys.platform == "win32":
        return _windows_pid_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # someone else's process, but it is running
    return True


def _windows_pid_alive(pid: int) -> bool:
    import ctypes  # noqa: PLC0415 - Windows only
    from ctypes import wintypes  # noqa: PLC0415

    process_query_limited_information = 0x1000
    still_active = 259
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # ty: ignore[unresolved-attribute]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)  # noqa: FBT003
    if not handle:
        # Access denied means it exists and belongs to someone else.
        access_denied = 5
        return ctypes.get_last_error() == access_denied  # ty: ignore[unresolved-attribute]
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == still_active
    finally:
        kernel32.CloseHandle(handle)
