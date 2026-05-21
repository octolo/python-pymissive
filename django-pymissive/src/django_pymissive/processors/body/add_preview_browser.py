"""Body processor: append browser-preview link to email bodies.

Opt-in — not included in :data:`~._base.DEFAULT_BODY_PROCESSORS`.

Dotted paths for settings / JSON fields::

    "django_pymissive.processors.body.add_preview_browser.add_preview_browser"
    "django_pymissive.processors.body.add_preview_browser.PreviewBrowserProcessor"
"""

from __future__ import annotations

from typing import Any

from ._base import MissiveBodyProcessor, _append_email_snippet


def add_preview_browser(
    content: str,
    *,
    missive=None,
    campaign=None,
    field_name: str | None = None,
    context: dict | None = None,
    **kwargs: Any,
) -> str:
    """Append ``show_preview_browser`` / ``_text`` to email bodies (after template render)."""
    return _append_email_snippet(
        content,
        missive=missive,
        campaign=campaign,
        field_name=field_name,
        html_attr="show_preview_browser",
        text_attr="show_preview_browser_text",
    )


class PreviewBrowserProcessor(MissiveBodyProcessor):
    """Class-based variant of :func:`add_preview_browser`."""

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
        return add_preview_browser(
            content,
            missive=missive,
            campaign=campaign,
            field_name=field_name,
            context=context,
            **kwargs,
        )
