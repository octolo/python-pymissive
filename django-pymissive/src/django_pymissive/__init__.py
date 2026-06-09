"""Django Missive - Django library for missive management."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("django-pymissive")
except PackageNotFoundError:
    __version__ = "0.0.0.dev"

from .shortcuts import send_missive, _shortcuts as _send_shortcuts  # noqa: E402

# Re-export all auto-generated send_<type>() helpers at package level
# e.g. ``from django_pymissive import send_email, send_sms, send_lre``
globals().update(_send_shortcuts)
