"""Infrastructure for the body-processor pipeline.

Shared resolution/invocation helpers, base class, defaults, and email-snippet
utilities used by every built-in body processor.
"""

from __future__ import annotations

from typing import Any, Iterable

from django.conf import settings
from django.utils.module_loading import import_string


# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

DEFAULT_BODY_PROCESSORS: list[str] = [
    "django_pymissive.processors.body.django_template.django_template_processor",
]

EMAIL_MISSIVE_TYPES = frozenset({"email", "email_marketing", "ere"})
EMAIL_BODY_HTML_FIELDS = frozenset({"body_html"})
EMAIL_BODY_TEXT_FIELDS = frozenset({"body_text"})


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

def get_default_body_processors() -> list:
    """Return the active default body-processor chain.

    Honors ``settings.PYMISSIVE_DEFAULT_BODY_PROCESSORS`` when set.
    """
    override = getattr(settings, "PYMISSIVE_DEFAULT_BODY_PROCESSORS", None)
    if override is not None:
        return list(override)
    return list(DEFAULT_BODY_PROCESSORS)


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class MissiveBodyProcessor:
    """Base class for class-based body processors.

    Subclass and override :meth:`process`. The default implementation is a
    no-op so subclasses only need to override the hook they care about.
    """

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
        return content


# ---------------------------------------------------------------------------
# Internal resolution / invocation
# ---------------------------------------------------------------------------

def _resolve_processor(processor: Any) -> tuple[Any, dict]:
    """Resolve a processor entry to ``(callable, extra_kwargs)``.

    Accepts a dotted-path string, a ``[path, kwargs]`` pair, a
    ``{"processor": ..., "kwargs": ...}`` dict, a callable, or a class.
    Class references are instantiated with no args.
    """
    extra_kwargs: dict = {}

    if isinstance(processor, dict):
        path = processor.get("processor") or processor.get("path")
        extra_kwargs = dict(processor.get("kwargs") or {})
        processor = path
    elif isinstance(processor, (list, tuple)) and len(processor) == 2:
        processor, extra_kwargs = processor[0], dict(processor[1] or {})

    if isinstance(processor, str):
        processor = import_string(processor)

    if isinstance(processor, type):
        processor = processor()

    return processor, extra_kwargs


def _call_processor(
    processor: Any,
    content: str,
    *,
    missive=None,
    campaign=None,
    field_name: str | None = None,
    context: dict | None = None,
    **kwargs: Any,
) -> str:
    """Invoke a resolved processor (instance with ``process`` or plain callable)."""
    if hasattr(processor, "process") and callable(processor.process):
        return processor.process(
            content,
            missive=missive,
            campaign=campaign,
            field_name=field_name,
            context=context,
            **kwargs,
        )
    if callable(processor):
        return processor(
            content,
            missive=missive,
            campaign=campaign,
            field_name=field_name,
            context=context,
            **kwargs,
        )
    raise TypeError(
        f"Processor {processor!r} is not callable and has no .process() method"
    )


def apply_body_processors(
    content: str,
    processors: Iterable[Any] | None,
    *,
    missive=None,
    campaign=None,
    field_name: str | None = None,
    context: dict | None = None,
) -> str:
    """Apply ``processors`` (in order) to ``content`` and return the result.

    Each processor receives the current content as the first positional arg
    and the same kwargs (``missive``, ``campaign``, ``field_name``, ``context``).
    """
    if not processors:
        return content
    for entry in processors:
        if entry is None:
            continue
        processor, extra_kwargs = _resolve_processor(entry)
        content = _call_processor(
            processor,
            content,
            missive=missive,
            campaign=campaign,
            field_name=field_name,
            context=context,
            **extra_kwargs,
        )
    return content


# ---------------------------------------------------------------------------
# Email-snippet helpers (shared by add_preview_browser / add_attachments_linked)
# ---------------------------------------------------------------------------

def _is_email_body_field(field_name: str | None) -> bool:
    return field_name in EMAIL_BODY_HTML_FIELDS or field_name in EMAIL_BODY_TEXT_FIELDS


def _is_email_missive(missive) -> bool:
    if missive is None:
        return False
    return (getattr(missive, "missive_type", None) or "").lower() in EMAIL_MISSIVE_TYPES


def _email_body_owner(*, missive=None, campaign=None):
    """Return the object that exposes ``show_*`` snippet properties."""
    return missive if missive is not None else campaign


def _append_email_snippet(
    content: str,
    *,
    missive=None,
    campaign=None,
    field_name: str | None,
    html_attr: str,
    text_attr: str,
) -> str:
    """Append email snippet; no-op if not email body or empty fragment. Text: ``\\n\\n``; HTML: ``<br>``."""
    if not content or not _is_email_body_field(field_name):
        return content
    if missive is not None and not _is_email_missive(missive):
        return content
    owner = _email_body_owner(missive=missive, campaign=campaign)
    if owner is None:
        return content
    if field_name in EMAIL_BODY_HTML_FIELDS:
        fragment = getattr(owner, html_attr, None) or ""
    else:
        fragment = getattr(owner, text_attr, None) or ""
    fragment = str(fragment).strip()
    if not fragment:
        return content
    if field_name in EMAIL_BODY_TEXT_FIELDS:
        content = content.rstrip("\n") + "\n\n"
        return f"{content}{fragment}"
    return f"{content}<br>{fragment}"
