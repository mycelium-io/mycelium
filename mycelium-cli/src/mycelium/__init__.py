"""Mycelium CLI — IoC/CFN coordination layer."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("mycelium-cli")
except PackageNotFoundError:
    __version__ = "0.0.0.dev"
