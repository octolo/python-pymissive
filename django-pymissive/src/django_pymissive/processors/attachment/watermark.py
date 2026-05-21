"""Attachment processor: stamp a watermark on PDF attachments.

Thin adapter around :func:`~django_pymissive.processors.pdf.watermark.watermark_processor`
that guards on ``attachment.is_pdf`` (or the ``%PDF-`` magic header) so the
same chain can safely run against mixed attachments (PDF, DOCX, JPG, …).

Dotted paths for settings / JSON fields::

    "django_pymissive.processors.attachment.watermark.watermark_pdf_attachments"
    "django_pymissive.processors.attachment.watermark.WatermarkPdfAttachmentsProcessor"
"""

from __future__ import annotations

from typing import Any

from ._base import MissiveAttachmentProcessor


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

    Accepts the same ``**kwargs`` as :func:`~django_pymissive.processors.pdf.watermark.watermark_processor`
    (``text``, ``alpha``, ``color``, ``font_size``, ``font_name``, ``rotation``).
    Configure via the JSON entry::

        ["django_pymissive.processors.attachment.watermark.watermark_pdf_attachments",
         {"text": "DRAFT", "alpha": 0.18}]
    """
    if not content_bytes:
        return content_bytes

    is_pdf = bool(getattr(attachment, "is_pdf", False)) or content_bytes[:5] == b"%PDF-"
    if not is_pdf:
        return content_bytes

    from django_pymissive.processors.pdf.watermark import watermark_processor

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
