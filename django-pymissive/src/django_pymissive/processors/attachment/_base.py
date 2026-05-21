"""Infrastructure for the attachment-processor pipeline.

Resolution / invocation helpers, base class, defaults, and the chain runner
used by every built-in attachment processor.
"""

from __future__ import annotations

from typing import Any, Iterable

from django.conf import settings
from django.utils.module_loading import import_string


# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

DEFAULT_ATTACHMENT_PROCESSORS: list = []


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

def get_default_attachment_processors() -> list:
    """Return the active default attachment-processor chain.

    Honors ``settings.PYMISSIVE_DEFAULT_ATTACHMENT_PROCESSORS`` when set.
    The built-in default is an empty list — attachments pass through unchanged
    unless the project opts in (e.g. stamp DRAFT on PDFs in non-prod envs).
    """
    override = getattr(settings, "PYMISSIVE_DEFAULT_ATTACHMENT_PROCESSORS", None)
    if override is not None:
        return list(override)
    return list(DEFAULT_ATTACHMENT_PROCESSORS)


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class MissiveAttachmentProcessor:
    """Base class for class-based attachment processors.

    Subclass and override :meth:`process`. Default implementation is a
    pass-through (returns the input bytes unchanged).
    """

    def process(
        self,
        missive,
        attachment,
        content_bytes: bytes,
        *,
        campaign=None,
        context: dict | None = None,
        **kwargs: Any,
    ) -> bytes:
        return content_bytes


# ---------------------------------------------------------------------------
# Internal resolution / invocation
# ---------------------------------------------------------------------------

def _resolve_processor(processor: Any) -> tuple[Any, dict]:
    """Resolve an entry to ``(callable_or_instance, extra_kwargs)``."""
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
    missive,
    attachment,
    content_bytes: bytes,
    *,
    campaign=None,
    context: dict | None = None,
    **kwargs: Any,
) -> bytes:
    if hasattr(processor, "process") and callable(processor.process):
        return processor.process(
            missive,
            attachment,
            content_bytes,
            campaign=campaign,
            context=context,
            **kwargs,
        )
    if callable(processor):
        return processor(
            missive,
            attachment,
            content_bytes,
            campaign=campaign,
            context=context,
            **kwargs,
        )
    raise TypeError(
        f"Attachment processor {processor!r} is not callable and has no .process() method"
    )


def apply_attachment_processors(
    missive,
    attachment,
    content_bytes: bytes,
    processors: Iterable[Any] | None,
    *,
    campaign=None,
    context: dict | None = None,
) -> bytes:
    """Run ``processors`` (in order) on ``content_bytes`` and return the result.

    Returns ``content_bytes`` unchanged when the chain is empty or ``None``.
    Each processor receives the previous processor's output.
    """
    if not processors:
        return content_bytes
    current = content_bytes
    for entry in processors:
        if entry is None:
            continue
        processor, extra_kwargs = _resolve_processor(entry)
        result = _call_processor(
            processor,
            missive,
            attachment,
            current,
            campaign=campaign,
            context=context,
            **extra_kwargs,
        )
        if result is None:
            continue
        current = result
    return current


def resolve_attachment_processors_for(attachment) -> list:
    """Resolve the processor chain that applies to ``attachment``.

    "Most specific wins": missive → campaign → defaults.
    """
    missive = attachment.missive if getattr(attachment, "missive_id", None) else None
    campaign = attachment.campaign if getattr(attachment, "campaign_id", None) else None

    if missive is not None:
        if missive.attachment_processors:
            return list(missive.attachment_processors)
        camp = campaign or (
            missive.campaign if getattr(missive, "campaign_id", None) else None
        )
        if camp is not None and camp.attachment_processors:
            return list(camp.attachment_processors)
        return get_default_attachment_processors()

    if campaign is not None:
        if campaign.attachment_processors:
            return list(campaign.attachment_processors)
        return get_default_attachment_processors()

    return get_default_attachment_processors()
