"""Processors package for django-pymissive.

Three sub-packages, one file per processor:

- :mod:`django_pymissive.processors.body` — body / template processors
- :mod:`django_pymissive.processors.attachment` — attachment-bytes processors
- :mod:`django_pymissive.processors.pdf` — PDF (first_document) processors

Legacy flat modules (``body_processors``, ``attachment_processors``,
``pdf_processors``) re-export everything from here for backward compatibility.
"""

from .body import (
    AttachmentsLinkedProcessor,
    MissiveBodyProcessor,
    PreviewBrowserProcessor,
    add_attachments_linked,
    add_preview_browser,
    apply_body_processors,
    django_template_processor,
    get_default_body_processors,
)
from .attachment import (
    MissiveAttachmentProcessor,
    WatermarkPdfAttachmentsProcessor,
    apply_attachment_processors,
    get_default_attachment_processors,
    resolve_attachment_processors_for,
    watermark_pdf_attachments,
)
from .pdf import (
    MissivePdfProcessor,
    WatermarkProcessor,
    WeasyprintRendererProcessor,
    apply_pdf_processors,
    get_default_pdf_processors,
    watermark_processor,
    weasyprint_renderer,
)

__all__ = [
    # body
    "MissiveBodyProcessor",
    "apply_body_processors",
    "get_default_body_processors",
    "django_template_processor",
    "add_preview_browser",
    "PreviewBrowserProcessor",
    "add_attachments_linked",
    "AttachmentsLinkedProcessor",
    # attachment
    "MissiveAttachmentProcessor",
    "apply_attachment_processors",
    "get_default_attachment_processors",
    "resolve_attachment_processors_for",
    "watermark_pdf_attachments",
    "WatermarkPdfAttachmentsProcessor",
    # pdf
    "MissivePdfProcessor",
    "apply_pdf_processors",
    "get_default_pdf_processors",
    "weasyprint_renderer",
    "WeasyprintRendererProcessor",
    "watermark_processor",
    "WatermarkProcessor",
]
