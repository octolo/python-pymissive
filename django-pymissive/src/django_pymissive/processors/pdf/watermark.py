"""PDF processor: stamp a diagonal text watermark on every page.

Requires ``pypdf`` and ``reportlab`` (``pip install django-pymissive[pdf]``).

Dotted paths for settings / JSON fields::

    "django_pymissive.processors.pdf.watermark.watermark_processor"
    "django_pymissive.processors.pdf.watermark.WatermarkProcessor"
"""

from __future__ import annotations

import math
from typing import Any, Sequence

from django.conf import settings

from ._base import MissivePdfProcessor


DEFAULT_WATERMARK_LINES: list[str] = ["nom", "date", "draft"]


def resolve_watermark_text(missive=None, campaign=None) -> list[str]:
    """missive → campaign → ``PYMISSIVE_WATERMARK`` → default lines."""
    if campaign is None and missive is not None:
        campaign = getattr(missive, "campaign", None) if getattr(missive, "campaign_id", None) else None

    for source in (missive, campaign):
        if source is None:
            continue
        cfg = getattr(source, "additional_config", None) or {}
        value = cfg.get("watermark") if isinstance(cfg, dict) else None
        lines = _coerce_lines(value)
        if lines:
            return lines

    settings_value = getattr(settings, "PYMISSIVE_WATERMARK", None)
    lines = _coerce_lines(settings_value)
    if lines:
        return lines

    return list(DEFAULT_WATERMARK_LINES)


def _coerce_lines(value: Any) -> list[str]:
    """``str`` (split on ``\\n``), sequence, or scalar → non-empty stripped lines."""
    if value is None:
        return []
    if isinstance(value, str):
        raw = value.split("\n")
    elif isinstance(value, Sequence):
        raw = list(value)
    else:
        raw = [value]
    lines = [str(line).strip() for line in raw]
    return [line for line in lines if line]


def _auto_font_size(
    lines: list[str],
    *,
    page_width: float,
    page_height: float,
    font_name: str,
    line_spacing: float,
    rotation: float = 45.0,
    max_fit_ratio: float = 0.92,
    floor: float = 12.0,
    ceiling: float = 110.0,
) -> float:
    """Font size so the rotated block's AABB fits the page (clamped to floor/ceiling)."""
    try:
        from reportlab.pdfbase.pdfmetrics import stringWidth
    except ImportError:  # pragma: no cover
        return 36.0

    theta = math.radians(rotation)
    cos_t = abs(math.cos(theta))
    sin_t = abs(math.sin(theta))

    ref_size = 100.0
    longest_at_ref = max(
        (stringWidth(line, font_name, ref_size) for line in lines),
        default=1.0,
    )
    alpha = max(longest_at_ref, 1.0) / ref_size
    beta = max(len(lines) * line_spacing, 1.0)

    width_coef = alpha * cos_t + beta * sin_t
    height_coef = alpha * sin_t + beta * cos_t

    size_for_width = (page_width * max_fit_ratio) / max(width_coef, 1e-6)
    size_for_height = (page_height * max_fit_ratio) / max(height_coef, 1e-6)

    return max(floor, min(ceiling, min(size_for_width, size_for_height)))


def watermark_processor(
    missive,
    pdf_bytes: bytes | None,
    *,
    campaign=None,
    context: dict | None = None,
    text: str | Sequence[str] | None = None,
    color: tuple[float, float, float] = (0.85, 0.1, 0.1),
    alpha: float = 0.25,
    font_size: int | float | None = None,
    font_name: str = "Helvetica-Bold",
    rotation: float = 45,
    line_spacing: float = 1.25,
    **kwargs: Any,
) -> bytes | None:
    """Diagonal watermark on every page. No-op if ``pdf_bytes`` is empty.

    ``text``: str or line list; default from :func:`resolve_watermark_text`.
    ``font_size``: auto-fit ceiling (not a fixed size), default cap 110pt.
    """
    if not pdf_bytes:
        return pdf_bytes
    try:
        from io import BytesIO

        from pypdf import PdfReader, PdfWriter
        from reportlab.pdfgen import canvas
    except ImportError as exc:  # pragma: no cover - exercised at runtime
        raise ImportError(
            "watermark_processor requires pypdf and reportlab. "
            "Install them with: pip install django-pymissive[pdf]"
        ) from exc

    if text is None:
        lines = resolve_watermark_text(missive=missive, campaign=campaign)
    else:
        lines = _coerce_lines(text)
        if not lines:
            lines = resolve_watermark_text(missive=missive, campaign=campaign)

    def _build_overlay_page(width: float, height: float, cx: float, cy: float):
        ceiling = float(font_size) if font_size else 110.0
        effective_size = _auto_font_size(
            lines,
            page_width=width,
            page_height=height,
            font_name=font_name,
            line_spacing=line_spacing,
            rotation=rotation,
            ceiling=ceiling,
        )
        line_height = effective_size * line_spacing
        total_height = len(lines) * line_height
        line_offsets = [
            total_height / 2 - (i + 0.5) * line_height for i in range(len(lines))
        ]

        buf = BytesIO()
        c = canvas.Canvas(buf, pagesize=(width, height))
        c.saveState()
        c.translate(cx, cy)
        c.rotate(rotation)
        r, g, b = color
        c.setFillColorRGB(r, g, b, alpha=alpha)
        c.setFont(font_name, effective_size)
        for line, y in zip(lines, line_offsets):
            c.drawCentredString(0, y, line)
        c.restoreState()
        c.showPage()
        c.save()
        buf.seek(0)
        return PdfReader(buf).pages[0]

    base = PdfReader(BytesIO(pdf_bytes))
    writer = PdfWriter()
    # Cache overlays by page geometry: typical PDFs have uniform page sizes
    # so we build a single overlay; mixed-size PDFs (e.g. an appended
    # landscape page) still get correctly-sized stamps.
    overlay_cache: dict[tuple, Any] = {}

    for page in base.pages:
        mb = page.mediabox
        width = float(mb.width)
        height = float(mb.height)
        left = float(mb.left)
        bottom = float(mb.bottom)
        cx = left + width / 2
        cy = bottom + height / 2

        key = (round(width, 3), round(height, 3), round(left, 3), round(bottom, 3))
        overlay_page = overlay_cache.get(key)
        if overlay_page is None:
            overlay_page = _build_overlay_page(width, height, cx, cy)
            overlay_cache[key] = overlay_page

        page.merge_page(overlay_page)
        writer.add_page(page)

    out = BytesIO()
    writer.write(out)
    return out.getvalue()


class WatermarkProcessor(MissivePdfProcessor):
    """Class-based variant of :func:`watermark_processor`."""

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
