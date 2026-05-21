"""PDF processor: render HTML body to PDF via WeasyPrint.

Default first-in-chain processor for ``first_document_processors``.

Dotted paths for settings / JSON fields::

    "django_pymissive.processors.pdf.weasyprint_renderer.weasyprint_renderer"
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.utils.module_loading import import_string

from ._base import MissivePdfProcessor


def weasyprint_renderer(
    missive,
    pdf_bytes: bytes | None,
    *,
    campaign=None,
    context: dict | None = None,
    **kwargs: Any,
) -> bytes:
    """Render the missive HTML body to PDF via WeasyPrint (or ``MISSIVEPDF_GENERATOR``).

    Delegates to the callable configured by ``settings.MISSIVEPDF_GENERATOR``
    (default: :func:`django_pymissive.pdf.body_to_pdf`).  The incoming
    ``pdf_bytes`` argument (previous chain output) is ignored: this processor
    always produces a fresh PDF from ``missive.first_document_compiled``.

    Runtime kwargs forwarded by ``Missive.body_to_pdf(**kwargs)`` (e.g.
    ``postal_recipient_pk``) are passed via ``context`` and forwarded to the
    underlying generator. Per-entry config kwargs (``**kwargs``) take
    precedence and are forwarded as well.
    """
    pdf_generator_path = getattr(
        settings, "MISSIVEPDF_GENERATOR", "django_pymissive.pdf.body_to_pdf"
    )
    pdf_generator = import_string(pdf_generator_path)
    runtime_kwargs = dict(context or {})
    runtime_kwargs.update(kwargs)
    return pdf_generator(missive, **runtime_kwargs)


class WeasyprintRendererProcessor(MissivePdfProcessor):
    """Class-based variant of :func:`weasyprint_renderer`."""

    def process(
        self,
        missive,
        pdf_bytes: bytes | None,
        *,
        campaign=None,
        context: dict | None = None,
        **kwargs: Any,
    ) -> bytes:
        return weasyprint_renderer(
            missive,
            pdf_bytes,
            campaign=campaign,
            context=context,
            **kwargs,
        )
