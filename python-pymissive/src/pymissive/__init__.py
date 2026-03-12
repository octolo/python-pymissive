"""Python Missive - Framework-agnostic messaging library."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("pymissive")
except PackageNotFoundError:
    __version__ = "0.0.0.dev"
