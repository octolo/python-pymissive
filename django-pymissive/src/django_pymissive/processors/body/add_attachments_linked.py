"""Body processor: append linked-attachment listing to email bodies.

Opt-in — not included in :data:`~._base.DEFAULT_BODY_PROCESSORS`.

Dotted paths for settings / JSON fields::

    "django_pymissive.processors.body.add_attachments_linked.add_attachments_linked"
    "django_pymissive.processors.body.add_attachments_linked.AttachmentsLinkedProcessor"
"""

from __future__ import annotations

from typing import Any

from ._base import MissiveBodyProcessor, _append_email_snippet


def add_attachments_linked(
    content: str,
    *,
    missive=None,
    campaign=None,
    field_name: str | None = None,
    context: dict | None = None,
    **kwargs: Any,
) -> str:
    """Append ``show_attachments_linked`` / ``_text`` to email bodies."""
    return _append_email_snippet(
        content,
        missive=missive,
        campaign=campaign,
        field_name=field_name,
        html_attr="show_attachments_linked",
        text_attr="show_attachments_linked_text",
    )


class AttachmentsLinkedProcessor(MissiveBodyProcessor):
    """Class-based variant of :func:`add_attachments_linked`."""

    def process(
        self,
        content: str,
        *,
        missive=None,
        campaign=None,
        field_name: str | None = None,
        context: dict | None = None,
        **kwargs: Any,
    ) -> str:
        return add_attachments_linked(
            content,
            missive=missive,
            campaign=campaign,
            field_name=field_name,
            context=context,
            **kwargs,
        )
