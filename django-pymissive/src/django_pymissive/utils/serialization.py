"""Serialization and display helpers."""

import json

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.utils.text import Truncator


SNAPSHOT_HTML_READ_MORE_LENGTH = 500


def serialize_model_for_context(obj) -> dict:
    """Plain dict for templates (no live model — avoids callable access like ``delete()``)."""
    data = {field.attname: field.value_from_object(obj) for field in obj._meta.concrete_fields}
    if callable(getattr(obj, "to_context_dict", None)):
        data.update(obj.to_context_dict())
    return data


def json_safe(value):
    """Return a JSON-compatible copy of ``value``."""
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder, default=str))


def snapshot_html_read_more(value: str | None) -> str:
    """Return an HTML-balanced excerpt of a rich-text snapshot."""
    if not value:
        return ""
    configured_length = getattr(
        settings,
        "PYMISSIVE_SNAPSHOT_HTML_READ_MORE_LENGTH",
        SNAPSHOT_HTML_READ_MORE_LENGTH,
    )
    try:
        length = max(1, int(configured_length))
    except (TypeError, ValueError):
        length = SNAPSHOT_HTML_READ_MORE_LENGTH
    return Truncator(value).chars(length, html=True)
