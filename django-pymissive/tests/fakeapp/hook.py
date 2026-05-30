"""Fake body processor for testing the hook/processor pipeline."""

_HTML_FIELDS = frozenset({"body_html", "first_document"})
_TEXT_FIELDS = frozenset({"body_text", "body_sms"})

MARKER_HTML = "<br><br><em>hook fakeapp added</em>"
MARKER_TEXT = "\n\nhook fakeapp added"


def add_fake_text(content, *, field_name=None, **kwargs):
    """Append a marker to the rendered content, formatted for HTML or plain text."""
    if not content:
        return content
    if field_name in _HTML_FIELDS:
        return f"{content}{MARKER_HTML}"
    if field_name in _TEXT_FIELDS:
        return f"{content.rstrip()}{MARKER_TEXT}"
    return content
