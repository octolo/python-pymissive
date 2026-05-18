"""Unit tests for ``django_pymissive.pdf_processors``.

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

from django_pymissive.pdf_processors import (
    DEFAULT_PDF_PROCESSORS,
    MissivePdfProcessor,
    apply_pdf_processors,
    get_default_pdf_processors,
    watermark_processor,
    weasyprint_renderer,
)


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
        "django_pymissive.pdf_processors.weasyprint_renderer",
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
