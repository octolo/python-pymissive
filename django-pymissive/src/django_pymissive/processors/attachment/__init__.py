"""Attachment processors sub-package."""

from ._base import (
    DEFAULT_ATTACHMENT_PROCESSORS,
    MissiveAttachmentProcessor,
    _call_processor,
    _resolve_processor,
    apply_attachment_processors,
    get_default_attachment_processors,
    resolve_attachment_processors_for,
)
from .watermark import WatermarkPdfAttachmentsProcessor, watermark_pdf_attachments

__all__ = [
    "DEFAULT_ATTACHMENT_PROCESSORS",
    "MissiveAttachmentProcessor",
    "apply_attachment_processors",
    "get_default_attachment_processors",
    "resolve_attachment_processors_for",
    "watermark_pdf_attachments",
    "WatermarkPdfAttachmentsProcessor",
]
