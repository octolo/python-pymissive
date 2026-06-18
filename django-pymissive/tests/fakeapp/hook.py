"""Fake body processor for testing the hook/processor pipeline."""

import time

_HTML_FIELDS = frozenset({"body_rich", "first_document"})
_TEXT_FIELDS = frozenset({"body_text", "phone_body_text"})

MARKER_HTML = "<br><br><em>hook fakeapp added</em>"
MARKER_TEXT = "\n\nhook fakeapp added"

DEFAULT_SLEEP_SECONDS = 5


def add_fake_text(content, *, field_name=None, **kwargs):
    """Append a marker to the rendered content, formatted for HTML or plain text."""
    if not content:
        return content
    if field_name in _HTML_FIELDS:
        return f"{content}{MARKER_HTML}"
    if field_name in _TEXT_FIELDS:
        return f"{content.rstrip()}{MARKER_TEXT}"
    return content


def sleep_processor(content, *, seconds=None, field_name=None, **kwargs):
    """Block for several seconds to exercise send/preview timeouts.

    Opt-in only — add to ``body_processors`` on a missive or campaign, e.g.::

        ["tests.fakeapp.hook.sleep_processor", {"seconds": 8}]

    Content is returned unchanged after the delay.
    """
    print("sleep_processor", seconds)
    time.sleep(seconds if seconds is not None else DEFAULT_SLEEP_SECONDS)
    return content
