# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Mycelium CLI — IoC/CFN coordination layer."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("mycelium-cli")
except PackageNotFoundError:
    __version__ = "0.0.0.dev"
