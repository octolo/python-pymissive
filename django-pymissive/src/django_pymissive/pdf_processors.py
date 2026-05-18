"""PDF processors pipeline for the postal first_document.

PDF processors are hooks that produce/transform the PDF rendered for a
postal/LRE missive's "first document" (the letter body sent as page 1 to
the provider, also displayed in the browser preview via PDF.js).

The chain produces ``bytes``. The first processor receives ``None`` as
input and is expected to *render* a PDF from scratch (typical case: the
default :func:`weasyprint_renderer` which converts the compiled HTML body
to a PDF via WeasyPrint). Subsequent processors receive the previous
processor's output and act as **post-processors** (watermark, signature,
append disclaimer pages, encrypt, etc.).

A processor is either:

- a callable ``processor(missive, pdf_bytes, *, campaign=None, context=None,
  **kwargs) -> bytes``;
- a class with a ``process(self, missive, pdf_bytes, *, campaign=None,
  context=None, **kwargs) -> bytes`` method (subclass
  :class:`MissivePdfProcessor`);
- a class instance exposing the same ``process`` method.

Processors are referenced as Python import paths (strings) stored in the
``first_document_processors`` JSON field on
:class:`~django_pymissive.models.Missive` and
:class:`~django_pymissive.models.MissiveCampaign`. Same entry shapes as
body_processors: a string path, ``[path, kwargs]`` pair, or
``{"processor": path, "kwargs": {...}}`` dict.
"""

from __future__ import annotations

from typing import Any, Iterable

from django.conf import settings
from django.utils.module_loading import import_string


class MissivePdfProcessor:
    """Base class for class-based PDF processors.

    Subclass and override :meth:`process`. The default implementation is a
    pass-through (returns the previous chain output unchanged) so subclasses
    can focus on the transformation they actually care about.
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


def weasyprint_renderer(
    missive,
    pdf_bytes: bytes | None,
    *,
    campaign=None,
    context: dict | None = None,
    **kwargs: Any,
) -> bytes:
    """Default first-page renderer: HTML body → PDF via :mod:`weasyprint`.

    Delegates to the function configured by ``MISSIVEPDF_GENERATOR``
    (defaulting to :func:`django_pymissive.pdf.body_to_pdf`). The
    ``pdf_bytes`` argument (the previous chain output) is ignored: this
    processor always produces a fresh PDF from
    ``missive.first_document_compiled``.

    Runtime kwargs forwarded by ``Missive.body_to_pdf(**kwargs)`` (e.g.
    ``postal_recipient_pk``) are passed through ``context`` and forwarded
    to the underlying generator. Per-entry config kwargs (``**kwargs``)
    take precedence and are forwarded as well.
    """
    pdf_generator_path = getattr(
        settings, "MISSIVEPDF_GENERATOR", "django_pymissive.pdf.body_to_pdf"
    )
    pdf_generator = import_string(pdf_generator_path)
    runtime_kwargs = dict(context or {})
    runtime_kwargs.update(kwargs)
    return pdf_generator(missive, **runtime_kwargs)


def watermark_processor(
    missive,
    pdf_bytes: bytes | None,
    *,
    campaign=None,
    context: dict | None = None,
    text: str = "DRAFT",
    color: tuple[float, float, float] = (0.85, 0.1, 0.1),
    alpha: float = 0.25,
    font_size: int = 90,
    font_name: str = "Helvetica-Bold",
    rotation: float = 45,
    **kwargs: Any,
) -> bytes | None:
    """Stamp a diagonal text watermark on every page of ``pdf_bytes``.

    Designed to run **after** :func:`weasyprint_renderer` (or any other
    renderer producing PDF bytes) in the ``first_document_processors``
    chain. Pure no-op when ``pdf_bytes`` is falsy, so it is safe to leave
    in the chain even when nothing was rendered upstream.

    Requires ``pypdf`` and ``reportlab`` (installed via
    ``django-pymissive[pdf]``); raises a clear :class:`ImportError`
    otherwise so misconfiguration is loud rather than silent.

    Parameters
    ----------
    text:
        Watermark text. Defaults to ``"DRAFT"``.
    color:
        ``(r, g, b)`` tuple, each component in ``[0, 1]``.
    alpha:
        Opacity in ``[0, 1]``.
    font_size:
        Watermark font size in points.
    font_name:
        Any font registered with reportlab (``Helvetica``,
        ``Helvetica-Bold``, ``Times-Roman``...).
    rotation:
        Rotation angle in degrees, counter-clockwise.

    Configure via the JSON entry::

        ["django_pymissive.pdf_processors.watermark_processor",
         {"text": "INTERNAL", "alpha": 0.15}]
    """
    if not pdf_bytes:
        return pdf_bytes
    try:
        from io import BytesIO

        from pypdf import PdfReader, PdfWriter
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
    except ImportError as exc:  # pragma: no cover - exercised at runtime
        raise ImportError(
            "watermark_processor requires pypdf and reportlab. "
            "Install them with: pip install django-pymissive[pdf]"
        ) from exc

    base = PdfReader(BytesIO(pdf_bytes))
    width, height = A4
    overlay_buf = BytesIO()
    c = canvas.Canvas(overlay_buf, pagesize=A4)
    c.saveState()
    c.translate(width / 2, height / 2)
    c.rotate(rotation)
    r, g, b = color
    c.setFillColorRGB(r, g, b, alpha=alpha)
    c.setFont(font_name, font_size)
    c.drawCentredString(0, 0, str(text))
    c.restoreState()
    c.showPage()
    c.save()
    overlay_buf.seek(0)
    overlay_page = PdfReader(overlay_buf).pages[0]

    writer = PdfWriter()
    for page in base.pages:
        page.merge_page(overlay_page)
        writer.add_page(page)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


class WatermarkProcessor(MissivePdfProcessor):
    """Class-based variant of :func:`watermark_processor` for symmetry.

    Configure via processor kwargs::

        ["django_pymissive.pdf_processors.WatermarkProcessor",
         {"text": "DRAFT", "alpha": 0.2}]
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
        return watermark_processor(
            missive,
            pdf_bytes,
            campaign=campaign,
            context=context,
            **kwargs,
        )


DEFAULT_PDF_PROCESSORS: list[str] = [
    "django_pymissive.pdf_processors.weasyprint_renderer",
]


def get_default_pdf_processors() -> list:
    """Return the default PDF processor chain.

    Honors ``settings.PYMISSIVE_DEFAULT_FIRST_DOCUMENT_PROCESSORS`` when set
    (use ``[]`` to fully disable PDF generation), otherwise falls back to
    :data:`DEFAULT_PDF_PROCESSORS` which renders via WeasyPrint.
    """
    override = getattr(settings, "PYMISSIVE_DEFAULT_FIRST_DOCUMENT_PROCESSORS", None)
    if override is not None:
        return list(override)
    return list(DEFAULT_PDF_PROCESSORS)


def _resolve_processor(processor: Any) -> tuple[Any, dict]:
    """Resolve an entry to ``(callable, extra_kwargs)``.

    Same input shapes as body_processors: dotted string, ``[path, kwargs]``
    pair, or ``{"processor": path, "kwargs": {...}}`` dict. Class refs are
    instantiated with no args.
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
    raise TypeError(f"PDF processor {processor!r} is not callable and has no .process() method")


def apply_pdf_processors(
    missive,
    processors: Iterable[Any] | None,
    *,
    campaign=None,
    context: dict | None = None,
) -> bytes | None:
    """Run ``processors`` (in order) and return the final PDF bytes.

    The first processor receives ``pdf_bytes=None`` and is expected to
    produce a PDF; subsequent processors receive the previous processor's
    output and may transform it. Returns ``None`` when the chain is empty.
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
