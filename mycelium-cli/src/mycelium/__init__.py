# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Mycelium CLI: IoC/CFN coordination layer."""

from importlib.metadata import PackageNotFoundError, version

from mycelium._console import use_utf8_console

# First, before any module creates a Rich Console (a no-op off Windows).
use_utf8_console()

try:
    __version__ = version("mycelium-cli")
except PackageNotFoundError:
    __version__ = "0.0.0.dev"
