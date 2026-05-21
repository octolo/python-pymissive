"""Body processor: Django template rendering.

Default first-in-chain processor that renders ``content`` as a Django
template against ``context``.  Subsequent processors in the chain operate
on the already-rendered output.

Dotted path for settings / JSON fields::

    "django_pymissive.processors.body.django_template.django_template_processor"
"""

from __future__ import annotations

from typing import Any

from django.template import Context, Template


# Fields whose output is consumed as HTML — autoescape stays ON to avoid XSS.
# Everything else (body_text, body_sms, subject, …) is plain text, so we turn
# autoescape OFF, otherwise ``'`` becomes ``&#x27;``, ``&`` becomes ``&amp;``,
# etc. in the rendered output.
HTML_TEMPLATE_FIELDS = frozenset({"body_html", "first_document"})


def django_template_processor(
    content: str,
    *,
    missive=None,
    campaign=None,
    field_name: str | None = None,
    context: dict | None = None,
    **kwargs: Any,
) -> str:
    """Render ``content`` as a Django template; autoescape only for HTML fields."""
    if not content:
        return content
    autoescape = field_name in HTML_TEMPLATE_FIELDS
    return Template(str(content)).render(
        Context(context or {}, autoescape=autoescape)
    )
