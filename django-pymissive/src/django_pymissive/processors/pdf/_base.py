"""Infrastructure for the PDF-processor pipeline (first_document / postal).

The chain produces ``bytes``.  The first processor receives ``pdf_bytes=None``
and must render a PDF from scratch; subsequent processors receive the previous
output and act as post-processors (watermark, append pages, sign, …).
"""

from __future__ import annotations

from typing import Any, Iterable

from django.conf import settings
from django.utils.module_loading import import_string


# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

DEFAULT_PDF_PROCESSORS: list[str] = [
    "django_pymissive.processors.pdf.weasyprint_renderer.weasyprint_renderer",
]


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

def get_default_pdf_processors() -> list:
    """Return the active default PDF-processor chain.

    Honors ``settings.PYMISSIVE_DEFAULT_FIRST_DOCUMENT_PROCESSORS`` when set
    (use ``[]`` to fully disable PDF generation). Falls back to
    :data:`DEFAULT_PDF_PROCESSORS` which renders via WeasyPrint.
    """
    override = getattr(settings, "PYMISSIVE_DEFAULT_FIRST_DOCUMENT_PROCESSORS", None)
    if override is not None:
        return list(override)
    return list(DEFAULT_PDF_PROCESSORS)


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class MissivePdfProcessor:
    """Base class for class-based PDF processors.

    Subclass and override :meth:`process`. Default implementation is a
    pass-through so subclasses only need to override the transformation
    they care about.
    """

    def process(
        self,
        missive,
        pdf_bytes: bytes | None,
        *,
        campaign=None,
        context: dict | None = None,
        **kwargs: Any,
    ) -> bytes | None:
        return pdf_bytes


# ---------------------------------------------------------------------------
# Internal resolution / invocation
# ---------------------------------------------------------------------------

def _resolve_processor(processor: Any) -> tuple[Any, dict]:
    """Resolve an entry to ``(callable, extra_kwargs)``."""
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
    pdf_bytes: bytes | None,
    *,
    campaign=None,
    context: dict | None = None,
    **kwargs: Any,
) -> bytes | None:
    """Invoke a resolved processor (instance with ``process`` or plain callable)."""
    if hasattr(processor, "process") and callable(processor.process):
        return processor.process(
            missive,
            pdf_bytes,
            campaign=campaign,
            context=context,
            **kwargs,
        )
    if callable(processor):
        return processor(
            missive,
            pdf_bytes,
            campaign=campaign,
            context=context,
            **kwargs,
        )
    raise TypeError(
        f"PDF processor {processor!r} is not callable and has no .process() method"
    )


def apply_pdf_processors(
    missive,
    processors: Iterable[Any] | None,
    *,
    campaign=None,
    context: dict | None = None,
) -> bytes | None:
    """Run ``processors`` (in order) and return the final PDF bytes.

    The first processor receives ``pdf_bytes=None`` and is expected to
    produce a PDF; subsequent processors may transform it.
    Returns ``None`` when the chain is empty.
    """
    if not processors:
        return None
    pdf_bytes: bytes | None = None
    for entry in processors:
        if entry is None:
            continue
        processor, extra_kwargs = _resolve_processor(entry)
        pdf_bytes = _call_processor(
            processor,
            missive,
            pdf_bytes,
            campaign=campaign,
            context=context,
            **extra_kwargs,
        )
    return pdf_bytes
