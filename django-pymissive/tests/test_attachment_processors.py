"""Unit tests for ``django_pymissive.processors.attachment``.

Covers the chain runner, the resolver helper
(``resolve_attachment_processors_for``), and the
:func:`watermark_pdf_attachments` adapter that delegates to
:func:`processors.pdf.watermark.watermark_processor` only for PDF attachments.
"""

from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.test import override_settings

from django_pymissive.processors.attachment import (
    DEFAULT_ATTACHMENT_PROCESSORS,
    MissiveAttachmentProcessor,
    apply_attachment_processors,
    get_default_attachment_processors,
    resolve_attachment_processors_for,
    watermark_pdf_attachments,
)


def _make_attachment(*, is_pdf=False, **extra):
    """Build a duck-typed attachment object for unit tests."""
    return SimpleNamespace(is_pdf=is_pdf, **extra)


def _appender(missive, attachment, content_bytes, *, suffix=b" + a", **kwargs):
    return (content_bytes or b"") + suffix


class _UpperProcessor(MissiveAttachmentProcessor):
    def process(self, missive, attachment, content_bytes, **kwargs):
        return content_bytes.upper()


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


def test_default_attachment_processors_is_empty_module_constant():
    """The module-level default is an empty list — tests/settings.py opts in."""
    assert DEFAULT_ATTACHMENT_PROCESSORS == []


def test_get_default_attachment_processors_falls_back_to_default():
    with override_settings(PYMISSIVE_DEFAULT_ATTACHMENT_PROCESSORS=None):
        assert get_default_attachment_processors() == []


def test_get_default_attachment_processors_honors_override():
    with override_settings(
        PYMISSIVE_DEFAULT_ATTACHMENT_PROCESSORS=["tests.test_attachment_processors._appender"]
    ):
        assert get_default_attachment_processors() == [
            "tests.test_attachment_processors._appender"
        ]


def test_get_default_attachment_processors_supports_empty_list():
    with override_settings(PYMISSIVE_DEFAULT_ATTACHMENT_PROCESSORS=[]):
        assert get_default_attachment_processors() == []


# ---------------------------------------------------------------------------
# apply_attachment_processors
# ---------------------------------------------------------------------------


def test_apply_attachment_processors_empty_chain_passes_through():
    assert apply_attachment_processors(None, None, b"hello", []) == b"hello"
    assert apply_attachment_processors(None, None, b"hello", None) == b"hello"


def test_apply_attachment_processors_runs_in_order():
    out = apply_attachment_processors(
        None,
        None,
        b"X",
        [
            "tests.test_attachment_processors._appender",  # → X + a
            ["tests.test_attachment_processors._appender", {"suffix": b"!"}],  # → X + a!
        ],
    )
    assert out == b"X + a!"


def test_apply_attachment_processors_class_based_uppercase():
    out = apply_attachment_processors(
        None,
        None,
        b"hello",
        ["tests.test_attachment_processors._UpperProcessor"],
    )
    assert out == b"HELLO"


def test_apply_attachment_processors_skips_none_entries():
    out = apply_attachment_processors(
        None,
        None,
        b"X",
        [None, "tests.test_attachment_processors._appender", None],
    )
    assert out == b"X + a"


def test_apply_attachment_processors_processor_returning_none_keeps_previous():
    """A processor returning None is treated as a no-op (chain continues)."""

    def void(missive, attachment, content_bytes, **kwargs):
        return None

    out = apply_attachment_processors(
        None,
        None,
        b"keep",
        [void, "tests.test_attachment_processors._appender"],
    )
    assert out == b"keep + a"


# ---------------------------------------------------------------------------
# watermark_pdf_attachments — PDF-only adapter
# ---------------------------------------------------------------------------


def _build_minimal_pdf() -> bytes:
    pytest.importorskip("reportlab")
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.drawString(100, 750, "Hello")
    c.showPage()
    c.save()
    return buf.getvalue()


def test_watermark_pdf_attachments_passthrough_when_no_bytes():
    att = _make_attachment(is_pdf=True)
    assert watermark_pdf_attachments(None, att, b"") == b""
    assert watermark_pdf_attachments(None, att, None) is None


def test_watermark_pdf_attachments_skips_non_pdf():
    """Non-PDF bytes pass through unchanged regardless of attachment.is_pdf."""
    att = _make_attachment(is_pdf=False)
    payload = b"this is plain text, not a PDF"
    assert watermark_pdf_attachments(None, att, payload, text="DRAFT") == payload


def test_watermark_pdf_attachments_skips_when_attachment_says_non_pdf_and_bytes_dont_match():
    att = _make_attachment(is_pdf=False)
    # Even though `is_pdf=False`, magic-bytes detection picks PDF up
    pytest.importorskip("pypdf")
    pdf = _build_minimal_pdf()
    out = watermark_pdf_attachments(None, att, pdf, text="DRAFT")
    assert out is not None and out[:5] == b"%PDF-"
    assert len(out) >= len(pdf)


def test_watermark_pdf_attachments_processes_pdf():
    pytest.importorskip("pypdf")
    pdf = _build_minimal_pdf()
    att = _make_attachment(is_pdf=True)
    out = watermark_pdf_attachments(None, att, pdf, text="WATERMARK_SENTINEL")
    assert out is not None and out[:5] == b"%PDF-"

    from pypdf import PdfReader

    reader = PdfReader(BytesIO(out))
    assert any(
        "WATERMARK_SENTINEL" in (p.extract_text() or "") for p in reader.pages
    ), "Watermark text should be visible in the watermarked PDF"


def test_watermark_pdf_attachments_handles_missing_is_pdf_attribute():
    """Defensive: attachment without ``is_pdf`` attr should still work via magic bytes."""
    pytest.importorskip("pypdf")
    pdf = _build_minimal_pdf()
    att = SimpleNamespace()  # no is_pdf attribute at all
    out = watermark_pdf_attachments(None, att, pdf, text="DRAFT")
    assert out[:5] == b"%PDF-"


# ---------------------------------------------------------------------------
# resolve_attachment_processors_for
# ---------------------------------------------------------------------------


def _attachment_with(missive=None, campaign=None):
    """Build a fake attachment exposing the attrs the resolver inspects."""
    return SimpleNamespace(
        missive=missive,
        missive_id=getattr(missive, "pk", None),
        campaign=campaign,
        campaign_id=getattr(campaign, "pk", None),
    )


def test_resolve_picks_missive_chain_first():
    missive = SimpleNamespace(
        pk=1,
        attachment_processors=["m1", "m2"],
        campaign=None,
        campaign_id=None,
    )
    att = _attachment_with(missive=missive)
    assert resolve_attachment_processors_for(att) == ["m1", "m2"]


def test_resolve_falls_back_to_campaign_when_missive_empty():
    campaign = SimpleNamespace(pk=2, attachment_processors=["c1"])
    missive = SimpleNamespace(
        pk=1,
        attachment_processors=[],
        campaign=campaign,
        campaign_id=campaign.pk,
    )
    att = _attachment_with(missive=missive)
    assert resolve_attachment_processors_for(att) == ["c1"]


def test_resolve_falls_back_to_defaults_when_both_empty():
    campaign = SimpleNamespace(pk=2, attachment_processors=[])
    missive = SimpleNamespace(
        pk=1,
        attachment_processors=[],
        campaign=campaign,
        campaign_id=campaign.pk,
    )
    att = _attachment_with(missive=missive)
    with override_settings(PYMISSIVE_DEFAULT_ATTACHMENT_PROCESSORS=["default1"]):
        assert resolve_attachment_processors_for(att) == ["default1"]


def test_resolve_for_campaign_owned_attachment():
    """Attachment owned directly by a campaign (no missive) uses campaign chain."""
    campaign = SimpleNamespace(pk=2, attachment_processors=["c1"])
    att = _attachment_with(campaign=campaign)
    assert resolve_attachment_processors_for(att) == ["c1"]


def test_resolve_for_attachment_with_no_owner():
    """Orphan attachment (neither missive nor campaign) → defaults."""
    att = SimpleNamespace(missive=None, missive_id=None, campaign=None, campaign_id=None)
    with override_settings(PYMISSIVE_DEFAULT_ATTACHMENT_PROCESSORS=["fallback"]):
        assert resolve_attachment_processors_for(att) == ["fallback"]
