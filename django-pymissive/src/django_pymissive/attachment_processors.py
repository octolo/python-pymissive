"""Attachment processors pipeline.

Attachment processors are hooks that transform the bytes of every
:class:`~django_pymissive.models.MissiveBaseAttachment` right before they
are handed to the provider via :meth:`MissiveBaseAttachment.get_serialized_attachment`.

The chain is configured on :class:`~django_pymissive.models.Missive` and
:class:`~django_pymissive.models.MissiveCampaign` via the
``attachment_processors`` JSONField — same shape as ``body_processors`` /
``first_document_processors`` and the same "most specific wins" rule
(missive → campaign → defaults). Per-attachment overrides are intentionally
not supported (it would be tedious to maintain per-file).

A processor is either:

- a callable ``processor(missive, attachment, content_bytes, *,
  campaign=None, context=None, **kwargs) -> bytes``;
- a class with a matching ``process`` method (subclass
  :class:`MissiveAttachmentProcessor`);
- an instance of such a class.

Processors that should only act on PDFs are expected to check
``attachment.is_pdf`` (or the file bytes' magic header) and pass through
otherwise — see :func:`watermark_pdf_attachments` for a reference
implementation.
"""

from __future__ import annotations

from typing import Any, Iterable

from django.conf import settings
from django.utils.module_loading import import_string


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


def watermark_pdf_attachments(
    missive,
    attachment,
    content_bytes: bytes,
    *,
    campaign=None,
    context: dict | None = None,
    **kwargs: Any,
) -> bytes:
    """Stamp a watermark on PDF attachments only; pass through everything else.

    Thin adapter around :func:`django_pymissive.pdf_processors.watermark_processor`
    that checks ``attachment.is_pdf`` first (and falls back to the ``%PDF-``
    magic header when the attachment object is unavailable). Non-PDF bytes
    are returned unchanged so the same chain can run safely against mixed
    attachments (PDF letters + DOCX + JPG + ...).

    Accepts the same ``**kwargs`` as :func:`watermark_processor`
    (``text``, ``alpha``, ``color``, ``font_size``, ``font_name``,
    ``rotation``); they are forwarded as-is. Configure via the JSON entry::

        ["django_pymissive.attachment_processors.watermark_pdf_attachments",
         {"text": "DRAFT", "alpha": 0.18}]
    """
    if not content_bytes:
        return content_bytes

    is_pdf = bool(getattr(attachment, "is_pdf", False)) or content_bytes[:5] == b"%PDF-"
    if not is_pdf:
        return content_bytes

    from .pdf_processors import watermark_processor

    return watermark_processor(
        missive,
        content_bytes,
        campaign=campaign,
        context=context,
        **kwargs,
    )


class WatermarkPdfAttachmentsProcessor(MissiveAttachmentProcessor):
    """Class-based variant of :func:`watermark_pdf_attachments`."""

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
        return watermark_pdf_attachments(
            missive,
            attachment,
            content_bytes,
            campaign=campaign,
            context=context,
            **kwargs,
        )


DEFAULT_ATTACHMENT_PROCESSORS: list = []


def get_default_attachment_processors() -> list:
    """Return the default attachment processor chain.

    Honors ``settings.PYMISSIVE_DEFAULT_ATTACHMENT_PROCESSORS`` when set.
    The unsetting default is an empty list — i.e. attachments pass through
    unchanged unless the user opts in (typical case: stamp DRAFT on PDFs
    in non-prod environments).
    """
    override = getattr(settings, "PYMISSIVE_DEFAULT_ATTACHMENT_PROCESSORS", None)
    if override is not None:
        return list(override)
    return list(DEFAULT_ATTACHMENT_PROCESSORS)


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

    Returns ``content_bytes`` unchanged when the chain is empty. Each
    processor receives the previous processor's output, so the chain
    composes naturally.
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
    """Resolve the chain that applies to ``attachment``.

    "Most specific wins": ``attachment.missive.attachment_processors`` if
    non-empty, else ``attachment.[missive.]campaign.attachment_processors``
    when set, else :func:`get_default_attachment_processors`.
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
