"""Django Missive - Django library for missive management."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("django-pymissive")
except PackageNotFoundError:
    __version__ = "0.0.0.dev"
