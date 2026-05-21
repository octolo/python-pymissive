"""Unit tests for ``django_pymissive.processors.pdf``.

Covers:

- chain runner semantics (empty / passthrough / order / kwargs);
- :func:`watermark_processor` requires pypdf+reportlab and produces valid PDFs;
- :func:`weasyprint_renderer` forwards runtime + entry kwargs to the underlying
  generator (mocked via ``MISSIVEPDF_GENERATOR``);
- ``PYMISSIVE_DEFAULT_FIRST_DOCUMENT_PROCESSORS`` override.
"""

from __future__ import annotations

from io import BytesIO
from unittest.mock import Mock

import pytest
from django.test import override_settings

from django_pymissive.processors.pdf import (
    DEFAULT_PDF_PROCESSORS,
    MissivePdfProcessor,
    apply_pdf_processors,
    get_default_pdf_processors,
    watermark_processor,
    weasyprint_renderer,
)
from django_pymissive.processors.pdf.watermark import _auto_font_size

# A4 in PostScript points (210 × 297 mm).
A4_W, A4_H = 595.275591, 841.889764
FONT = "Helvetica-Bold"
LINE_SPACING = 1.25


def _build_minimal_pdf() -> bytes:
    """Create a tiny single-page PDF in memory using reportlab."""
    pytest.importorskip("reportlab")
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.drawString(100, 750, "Hello world")
    c.showPage()
    c.save()
    return buf.getvalue()


def _stub_renderer(missive, pdf_bytes, *, campaign=None, context=None, **kwargs):
    """Renderer stub: produces some sentinel bytes regardless of inputs."""
    return b"%PDF-FAKE\n" + (pdf_bytes or b"")


def _appender(missive, pdf_bytes, *, campaign=None, context=None, suffix=b" + ext", **kwargs):
    """Postprocessor stub: appends bytes to confirm chain ordering."""
    return (pdf_bytes or b"") + suffix


class _AppenderClass(MissivePdfProcessor):
    def process(self, missive, pdf_bytes, *, campaign=None, context=None, suffix=b" / cls", **kwargs):
        return (pdf_bytes or b"") + suffix


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


def test_default_chain_uses_weasyprint_renderer():
    assert DEFAULT_PDF_PROCESSORS == [
        "django_pymissive.processors.pdf.weasyprint_renderer.weasyprint_renderer",
    ]


def test_get_default_pdf_processors_falls_back_to_default():
    with override_settings(PYMISSIVE_DEFAULT_FIRST_DOCUMENT_PROCESSORS=None):
        assert get_default_pdf_processors() == list(DEFAULT_PDF_PROCESSORS)


def test_get_default_pdf_processors_honors_override():
    custom = ["tests.test_pdf_processors._stub_renderer"]
    with override_settings(PYMISSIVE_DEFAULT_FIRST_DOCUMENT_PROCESSORS=custom):
        assert get_default_pdf_processors() == custom


def test_get_default_pdf_processors_supports_empty_list():
    """Empty list = explicitly disable PDF generation."""
    with override_settings(PYMISSIVE_DEFAULT_FIRST_DOCUMENT_PROCESSORS=[]):
        assert get_default_pdf_processors() == []


# ---------------------------------------------------------------------------
# apply_pdf_processors
# ---------------------------------------------------------------------------


def test_apply_pdf_processors_empty_chain_returns_none():
    assert apply_pdf_processors(None, []) is None
    assert apply_pdf_processors(None, None) is None


def test_apply_pdf_processors_runs_renderer_then_postprocessors():
    out = apply_pdf_processors(
        None,
        [
            "tests.test_pdf_processors._stub_renderer",
            "tests.test_pdf_processors._appender",
        ],
    )
    assert out == b"%PDF-FAKE\n + ext"


def test_apply_pdf_processors_first_receives_none_then_chains():
    captured = []

    def renderer(missive, pdf_bytes, **kwargs):
        captured.append(("renderer_in", pdf_bytes))
        return b"R"

    def post(missive, pdf_bytes, **kwargs):
        captured.append(("post_in", pdf_bytes))
        return pdf_bytes + b"P"

    out = apply_pdf_processors(None, [renderer, post])
    assert out == b"RP"
    assert captured == [("renderer_in", None), ("post_in", b"R")]


def test_apply_pdf_processors_skips_none_entries():
    out = apply_pdf_processors(
        None,
        [None, "tests.test_pdf_processors._stub_renderer", None],
    )
    assert out == b"%PDF-FAKE\n"


def test_apply_pdf_processors_class_based_processor():
    out = apply_pdf_processors(
        None,
        [
            "tests.test_pdf_processors._stub_renderer",
            ["tests.test_pdf_processors._AppenderClass", {"suffix": b" / X"}],
        ],
    )
    assert out == b"%PDF-FAKE\n / X"


def test_apply_pdf_processors_per_entry_kwargs():
    out = apply_pdf_processors(
        None,
        [
            "tests.test_pdf_processors._stub_renderer",
            ["tests.test_pdf_processors._appender", {"suffix": b" + custom"}],
        ],
    )
    assert out == b"%PDF-FAKE\n + custom"


# ---------------------------------------------------------------------------
# watermark_processor
# ---------------------------------------------------------------------------


def test_watermark_processor_passthrough_when_no_input():
    assert watermark_processor(None, None) is None
    assert watermark_processor(None, b"") == b""


def test_watermark_processor_produces_valid_pdf():
    pytest.importorskip("pypdf")
    pytest.importorskip("reportlab")

    plain = _build_minimal_pdf()
    out = watermark_processor(None, plain, text="DRAFT", alpha=0.2)

    assert out is not None
    assert out[:5] == b"%PDF-", "Output must remain a valid PDF"
    assert len(out) > len(plain), "Watermarked PDF should be at least as large as the input"


def test_watermark_processor_preserves_page_count():
    pytest.importorskip("pypdf")
    pytest.importorskip("reportlab")

    plain = _build_minimal_pdf()
    out = watermark_processor(None, plain, text="DRAFT")

    from pypdf import PdfReader

    plain_pages = len(PdfReader(BytesIO(plain)).pages)
    out_pages = len(PdfReader(BytesIO(out)).pages)
    assert plain_pages == out_pages == 1


def test_watermark_processor_text_is_embedded():
    """Sanity check: the watermark text appears somewhere in the output stream."""
    pytest.importorskip("pypdf")
    pytest.importorskip("reportlab")

    plain = _build_minimal_pdf()
    out = watermark_processor(None, plain, text="WATERMARK_SENTINEL")
    # Reportlab encodes text as part of the content stream; check via pypdf
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(out))
    found = any("WATERMARK_SENTINEL" in (page.extract_text() or "") for page in reader.pages)
    assert found, "Watermark text should be visible after rendering"


# ---------------------------------------------------------------------------
# watermark auto-fit (font_size selection by text length / line count)
# ---------------------------------------------------------------------------


def _auto(lines, **overrides):
    """Shorthand: auto-fit font size on an A4 page with the default knobs."""
    kwargs = {
        "page_width": A4_W,
        "page_height": A4_H,
        "font_name": FONT,
        "line_spacing": LINE_SPACING,
    }
    kwargs.update(overrides)
    return _auto_font_size(lines, **kwargs)


def test_auto_font_size_decreases_with_line_length():
    """Same line count, growing text → strictly decreasing font size.

    Length range chosen so we're past the ceiling plateau (short text saturates
    at ``ceiling``) but still above the floor (huge text saturates at ``floor``);
    in that band the chosen size is purely a function of the width budget and
    must shrink monotonically.
    """
    pytest.importorskip("reportlab")

    # 15/30/60/100 chars: past the ceiling plateau, above the floor on A4
    # with Helvetica-Bold for the new rotated-AABB auto-fit (which hits the
    # 12pt floor around ~114 chars for a single line).
    sizes = [_auto(["x" * n]) for n in (15, 30, 60, 100)]
    assert sizes == sorted(sizes, reverse=True), (
        f"font_size must shrink monotonically as text grows: {sizes}"
    )
    assert all(a > b for a, b in zip(sizes, sizes[1:])), (
        f"every step must be strictly smaller: {sizes}"
    )


def test_auto_font_size_decreases_with_line_count():
    """Fixed line length, growing line count → strictly decreasing font size.

    Starts at 3 lines because 1–2 lines of a short word saturate at the
    ``ceiling`` — past the plateau, every extra line further constrains the
    perpendicular budget.
    """
    pytest.importorskip("reportlab")

    line = "watermark"  # short enough that height (not width) drives the size
    sizes = [_auto([line] * n) for n in (3, 4, 5, 6, 8, 10)]
    assert sizes == sorted(sizes, reverse=True), (
        f"font_size must shrink as more lines are stacked: {sizes}"
    )
    assert all(a > b for a, b in zip(sizes, sizes[1:])), (
        f"every step must be strictly smaller: {sizes}"
    )


def test_auto_font_size_saturates_at_ceiling_for_short_text():
    """Tiny watermark text should not balloon past the ceiling (no division-by-zero
    on whitespace either)."""
    pytest.importorskip("reportlab")

    ceiling = 110.0
    for short in (["DRAFT"], ["x"], ["A", "B"], ["short"]):
        assert _auto(short, ceiling=ceiling) == ceiling, short


def test_auto_font_size_respects_floor_for_huge_text():
    """A pathologically long watermark must clamp to the floor, not vanish."""
    pytest.importorskip("reportlab")

    floor = 12.0
    huge = ["société - monsieur Aurelien Gustave prevault" * 20] * 3
    size = _auto(huge, floor=floor, ceiling=110.0)
    assert size == floor, (
        f"Expected clamp to floor={floor} for very long text, got {size}"
    )


def test_auto_font_size_respects_ceiling_for_tiny_text():
    """A tiny single character must not balloon past the ceiling."""
    pytest.importorskip("reportlab")

    ceiling = 110.0
    size = _auto(["."], floor=12.0, ceiling=ceiling)
    assert size == ceiling, (
        f"Expected clamp to ceiling={ceiling} for trivial text, got {size}"
    )


def test_auto_font_size_always_within_bounds():
    """Across a wide range of inputs, the result must stay in [floor, ceiling]."""
    pytest.importorskip("reportlab")

    floor, ceiling = 12.0, 110.0
    cases = [
        ["x"],
        ["DRAFT"],
        ["société - monsieur Aurelien Gustave prevault", "2026 12 05 15:15"],
        ["a" * 200],
        ["line"] * 10,
        ["société exemple",
         "M. Aurelien Gustave prevault",
         "DRAFT — NE PAS DIFFUSER",
         "réf. dossier 2026/12-005",
         "généré 2026-12-05 15:15"],
    ]
    for lines in cases:
        size = _auto(lines, floor=floor, ceiling=ceiling)
        assert floor <= size <= ceiling, (
            f"font_size {size} out of [{floor}, {ceiling}] for {lines!r}"
        )


def test_watermark_processor_long_text_stays_legible_via_floor():
    """End-to-end: rendering with a huge watermark still produces a valid PDF."""
    pytest.importorskip("pypdf")
    pytest.importorskip("reportlab")

    plain = _build_minimal_pdf()
    long_lines = [
        "société - monsieur Aurelien Gustave prevault " * 5,
        "2026 12 05 15:15 — référence dossier ABC/123/456",
        "DRAFT — NE PAS DIFFUSER",
    ]
    out = watermark_processor(None, plain, text=long_lines, alpha=0.18)
    assert out is not None
    assert out[:5] == b"%PDF-", "Output must remain a valid PDF even with long text"

    from pypdf import PdfReader

    reader = PdfReader(BytesIO(out))
    text = "".join(page.extract_text() or "" for page in reader.pages)
    # All three lines must remain present (clamp to floor, never drop content).
    assert "soci" in text
    assert "2026" in text
    assert "DRAFT" in text


# ---------------------------------------------------------------------------
# End-to-end font-size checks: parse the actual Tf operator inscribed in the
# output PDF by watermark_processor (not the internal helper alone) and assert
# the same "longer text ⇒ smaller font, but never below the floor" contract.
# ---------------------------------------------------------------------------


def _watermark_font_size(pdf_bytes: bytes) -> float:
    """Return the font size used by the *watermark overlay* in ``pdf_bytes``.

    ``watermark_processor`` merges the overlay's content stream after the
    base page's, so the **last** ``Tf`` (Set Text Font) operator in the
    composed page is the watermark's. Robust to whatever font/size the
    base PDF was originally drawn with.
    """
    from pypdf import PdfReader
    from pypdf.generic import ContentStream

    reader = PdfReader(BytesIO(pdf_bytes))
    page = reader.pages[0]
    contents = page.get_contents()
    if contents is None:
        raise AssertionError("Watermarked PDF has no content stream")
    cs = ContentStream(contents, reader)
    sizes = [float(operands[-1]) for operands, op in cs.operations if op == b"Tf"]
    if not sizes:
        raise AssertionError("No 'Tf' operator found in the watermarked PDF")
    return sizes[-1]


def test_watermark_processor_font_size_shrinks_via_processor():
    """Through the full processor, growing the watermark text strictly
    shrinks the embedded font size (above the floor, below the ceiling)."""
    pytest.importorskip("pypdf")
    pytest.importorskip("reportlab")

    plain = _build_minimal_pdf()
    # Lengths chosen so the auto-fit is in the width-driven band on A4
    # (above the ceiling plateau for short text, above the floor for huge text).
    sizes = [
        _watermark_font_size(watermark_processor(None, plain, text="x" * n))
        for n in (15, 30, 60, 100)
    ]
    assert sizes == sorted(sizes, reverse=True), (
        f"font size embedded in the PDF must shrink as the text grows: {sizes}"
    )
    assert all(a > b for a, b in zip(sizes, sizes[1:])), sizes


def test_watermark_processor_font_size_floor_via_processor():
    """Pathological text ⇒ embedded size is the floor (12pt), not 0/None."""
    pytest.importorskip("pypdf")
    pytest.importorskip("reportlab")

    plain = _build_minimal_pdf()
    huge = ["société - monsieur Aurelien Gustave prevault" * 20] * 3
    out = watermark_processor(None, plain, text=huge)
    assert _watermark_font_size(out) == pytest.approx(12.0, abs=1e-6)


def test_watermark_processor_font_size_ceiling_via_processor():
    """Tiny text ⇒ embedded size is the ceiling (110pt), not unbounded."""
    pytest.importorskip("pypdf")
    pytest.importorskip("reportlab")

    plain = _build_minimal_pdf()
    out = watermark_processor(None, plain, text="DRAFT")
    assert _watermark_font_size(out) == pytest.approx(110.0, abs=1e-6)


def test_watermark_processor_font_size_in_bounds_via_processor():
    """End-to-end safety net: every reasonable input lands within [floor, ceiling]."""
    pytest.importorskip("pypdf")
    pytest.importorskip("reportlab")

    plain = _build_minimal_pdf()
    cases = [
        "DRAFT",
        "société - monsieur Aurelien Gustave prevault\n2026 12 05 15:15",
        ["nom", "date", "draft"],
        ["a" * 200],
        ["line"] * 10,
    ]
    for text in cases:
        size = _watermark_font_size(watermark_processor(None, plain, text=text))
        assert 12.0 <= size <= 110.0, f"font_size {size} out of bounds for {text!r}"


def test_watermark_block_does_not_overflow_the_page_when_rotated():
    """Regression test for the multi-line-watermark overflow.

    With the previous heuristic (text width bounded by ``page_diagonal``,
    line height bounded *independently* by ``min(W,H)``), a centred,
    rotated multi-line watermark like::

        ["ceci est un vrai test assez long", "celle la est aussi long", "draft"]

    overshot the A4 page width by ~150pt because the rotated bounding box
    cumulates the text width AND the block height along each page axis.

    The fix solves the proper geometric inequalities
    ``α·s·|cos θ| + β·s·|sin θ| ≤ page_width`` (and symmetric for height),
    so the rotated AABB must fit inside the page on **both** axes.
    """
    pytest.importorskip("reportlab")
    from reportlab.pdfbase.pdfmetrics import stringWidth

    lines = [
        "ceci est un vrai test assez long",
        "celle la est aussi long",
        "draft",
    ]
    size = _auto(lines)

    # Rotated AABB at 45° for a (W_text x H_block) block centred on origin:
    #   Δx = (W_text·|cos θ| + H_block·|sin θ|) / 2
    #   Δy = (W_text·|sin θ| + H_block·|cos θ|) / 2
    import math as _m

    theta = _m.radians(45)
    c, s_ = abs(_m.cos(theta)), abs(_m.sin(theta))
    w_text = max(stringWidth(line, FONT, size) for line in lines)
    h_block = len(lines) * size * LINE_SPACING
    extent_x = w_text * c + h_block * s_
    extent_y = w_text * s_ + h_block * c

    assert extent_x <= A4_W, (
        f"watermark rotated AABB width {extent_x:.1f}pt overflows A4 page "
        f"width {A4_W:.1f}pt (font_size={size:.2f}pt)"
    )
    assert extent_y <= A4_H, (
        f"watermark rotated AABB height {extent_y:.1f}pt overflows A4 page "
        f"height {A4_H:.1f}pt (font_size={size:.2f}pt)"
    )


def test_watermark_font_size_kwarg_is_a_ceiling_not_a_pin():
    """Passing ``font_size=N`` must NOT pin the size to N — it only caps it.

    This is the contract that lets users say "I want a 60pt watermark at
    most" without losing the auto-shrink behaviour on long texts.
    """
    pytest.importorskip("pypdf")
    pytest.importorskip("reportlab")

    plain = _build_minimal_pdf()
    cap = 60.0

    # Short text → would naturally pick 110pt without the cap; with cap=60
    # it must clamp down to 60pt.
    short = _watermark_font_size(
        watermark_processor(None, plain, text="DRAFT", font_size=cap)
    )
    assert short == pytest.approx(cap, abs=1e-6), (
        f"short text with font_size={cap} should saturate at the cap, got {short}"
    )

    # Long text → naturally smaller than the cap; the cap must NOT inflate
    # it (no min/max swap), AND auto-shrink must still kick in.
    long = _watermark_font_size(
        watermark_processor(None, plain, text="x" * 60, font_size=cap)
    )
    assert long < cap, (
        f"long text must still auto-shrink below the cap ({cap}pt), got {long}"
    )
    # And it must shrink monotonically as the text grows, even with the cap on
    # (until the floor is reached).
    longer = _watermark_font_size(
        watermark_processor(None, plain, text="x" * 90, font_size=cap)
    )
    assert longer < long, (
        f"longer text must shrink further below the cap: {longer} vs {long}"
    )

    # Pathological text → still bottoms out at the floor (12pt), cap unchanged.
    huge = _watermark_font_size(
        watermark_processor(None, plain, text=["x" * 800] * 3, font_size=cap)
    )
    assert huge == pytest.approx(12.0, abs=1e-6), (
        f"pathological text should still clamp to the 12pt floor, got {huge}"
    )


# ---------------------------------------------------------------------------
# weasyprint_renderer
# ---------------------------------------------------------------------------


def _record_call(missive, **kwargs):
    """Capture-everything generator stub used as MISSIVEPDF_GENERATOR."""
    _record_call.calls.append({"missive": missive, **kwargs})
    return b"%PDF-RECORDED"


_record_call.calls = []  # type: ignore[attr-defined]


def test_weasyprint_renderer_forwards_runtime_kwargs(settings):
    _record_call.calls.clear()
    settings.MISSIVEPDF_GENERATOR = "tests.test_pdf_processors._record_call"

    out = weasyprint_renderer(
        Mock(name="missive"),
        None,
        context={"postal_recipient_pk": 42},
    )
    assert out == b"%PDF-RECORDED"
    assert len(_record_call.calls) == 1
    assert _record_call.calls[0]["postal_recipient_pk"] == 42


def test_weasyprint_renderer_entry_kwargs_take_precedence(settings):
    _record_call.calls.clear()
    settings.MISSIVEPDF_GENERATOR = "tests.test_pdf_processors._record_call"

    weasyprint_renderer(
        Mock(name="missive"),
        None,
        context={"flag": "from-context"},
        flag="from-entry",
    )
    assert _record_call.calls[0]["flag"] == "from-entry"


def test_weasyprint_renderer_ignores_previous_pdf_bytes(settings):
    """The default renderer always re-renders, never composes on previous bytes."""
    _record_call.calls.clear()
    settings.MISSIVEPDF_GENERATOR = "tests.test_pdf_processors._record_call"

    out = weasyprint_renderer(Mock(name="missive"), b"existing-bytes")
    assert out == b"%PDF-RECORDED"  # NOT b"existing-bytes" + anything
