"""Fake body processor for testing the hook/processor pipeline."""

import logging
import time

logger = logging.getLogger(__name__)

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


def log_progress(scheduled):
    """Log the current campaign-send counts. Test ``PYMISSIVE_PROGRESS_HOOK``."""
    from django_pymissive.models.scheduler import format_average_send_speed

    line = (
        f"Campaign {scheduled.campaign_id} progress: "
        f"{scheduled.sent_count}/{scheduled.total_count} ({scheduled.progress}%)"
    )
    speed = format_average_send_speed(scheduled.average_send_speed)
    if speed:
        line = f"{line} — {speed}/send"
    if scheduled.cancelled_at:
        line = f"{line} [{scheduled.cancel_reason or 'cancelled'}]"
    logger.info(line)


def sleep_processor(content, *, seconds=None, field_name=None, **kwargs):
    """Block for several seconds to exercise send/preview timeouts.

    Opt-in only — add to ``body_processors`` on a missive or campaign, e.g.::

        ["tests.fakeapp.hook.sleep_processor", {"seconds": 8}]

    Content is returned unchanged after the delay.
    """
    logger.info("sleep_processor: %s s", seconds)
    time.sleep(seconds if seconds is not None else DEFAULT_SLEEP_SECONDS)
    return content
