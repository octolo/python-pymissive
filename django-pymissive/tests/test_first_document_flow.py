"""Integration tests for the first-document / attachment / duplicate flows.

Exercises the model code paths that were touched by the new hook system:

- :meth:`Missive.generate_first_document` creates an ``ATTACHMENT``-typed
  row (priority 0) and refreshes it on subsequent calls — without ever
  overwriting an unrelated virtual attachment.
- :meth:`Missive.duplicate_missive` copies regular AND virtual
  attachments while excluding the first-document row (regenerated on
  demand).
- :meth:`MissiveBaseAttachment.get_serialized_attachment` runs the
  ``attachment_processors`` chain on the bytes (and skips the
  first-document row to avoid double watermarking).
- ``MissiveBaseAttachment.is_pdf`` correctly detects PDFs for both
  regular and virtual attachments.
"""

from __future__ import annotations

from io import BytesIO

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile

from django_pymissive.models.attachment import (
    FIRST_DOCUMENT_PRIORITY,
    MissiveBaseAttachment,
)
from django_pymissive.models.choices import (
    MissiveAttachmentType,
    MissiveThreadType,
)
from django_pymissive.models.missive import Missive
from tests.fakeapp.models import PdfDocument

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Module-level capture helpers (reachable by dotted path in settings).
# ---------------------------------------------------------------------------


_attachment_calls: list[dict] = []


def _capturing_attachment_processor(
    missive, attachment, content_bytes, *, campaign=None, context=None, **kwargs
) -> bytes:
    _attachment_calls.append({
        "missive": missive,
        "attachment_pk": attachment.pk,
        "is_first_document": attachment.is_first_document,
        "content_in": content_bytes,
        "campaign": campaign,
    })
    return content_bytes + b" + processed"


def _record_renderer(missive, pdf_bytes, *, campaign=None, context=None, **kwargs) -> bytes:
    """Sentinel renderer for first_document tests — never calls weasyprint."""
    return b"%PDF-FIRST-DOC"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_lre_missive(**overrides) -> Missive:
    defaults = {
        "missive_type": "lre",
        "subject": "LRE",
        "body_html": "<p>letter body</p>",
    }
    defaults.update(overrides)
    return Missive.objects.create(**defaults)


def _make_email_missive(**overrides) -> Missive:
    defaults = {
        "missive_type": "email",
        "subject": "Email",
        "body_html": "<p>hi</p>",
    }
    defaults.update(overrides)
    return Missive.objects.create(**defaults)


def _attach_pdf(missive, *, name="doc.pdf", content=b"%PDF-1.4 fake") -> MissiveBaseAttachment:
    return MissiveBaseAttachment.objects.create(
        missive=missive,
        attachment_type=MissiveAttachmentType.ATTACHMENT,
        attachment_file=ContentFile(content, name=name),
        linked=False,
    )


def _attach_virtual_pdf(missive, doc: PdfDocument) -> MissiveBaseAttachment:
    return MissiveBaseAttachment.objects.create(
        missive=missive,
        attachment_type=MissiveAttachmentType.VIRTUAL_ATTACHMENT,
        attachment_content_type=ContentType.objects.get_for_model(PdfDocument),
        attachment_object_id=doc.pk,
        attachment_object_arguments={"method": "retrieve_attachment"},
        linked=False,
    )


# ---------------------------------------------------------------------------
# generate_first_document
# ---------------------------------------------------------------------------


def test_generate_first_document_creates_attachment_row(settings):
    """First call creates a single ATTACHMENT-typed row at priority 0."""
    settings.PYMISSIVE_DEFAULT_FIRST_DOCUMENT_PROCESSORS = [
        "tests.test_first_document_flow._record_renderer",
    ]
    missive = _make_lre_missive()

    att = missive.generate_first_document()

    assert att is not None
    assert att.attachment_type == MissiveAttachmentType.ATTACHMENT
    assert att.priority == FIRST_DOCUMENT_PRIORITY
    assert att.is_first_document is True
    assert att.attachment_file.read() == b"%PDF-FIRST-DOC"


def test_generate_first_document_is_idempotent(settings):
    """Second call refreshes the existing row instead of creating a duplicate."""
    settings.PYMISSIVE_DEFAULT_FIRST_DOCUMENT_PROCESSORS = [
        "tests.test_first_document_flow._record_renderer",
    ]
    missive = _make_lre_missive()
    first = missive.generate_first_document()
    second = missive.generate_first_document()

    assert first.pk == second.pk
    assert (
        missive.to_missiveattachment.filter(
            attachment_type=MissiveAttachmentType.ATTACHMENT,
            priority=FIRST_DOCUMENT_PRIORITY,
        ).count()
        == 1
    )


def test_generate_first_document_does_not_overwrite_virtual_attachment(settings):
    """Regression: a virtual attachment whose path happens to look like the
    first-document filename must NOT be overwritten by ``generate_first_document``.

    The filter looks up by ``attachment_type=ATTACHMENT`` AND
    ``priority=FIRST_DOCUMENT_PRIORITY`` exclusively.
    """
    settings.PYMISSIVE_DEFAULT_FIRST_DOCUMENT_PROCESSORS = [
        "tests.test_first_document_flow._record_renderer",
    ]
    missive = _make_lre_missive()

    doc = PdfDocument.objects.create(name="user-doc.pdf")
    virtual = MissiveBaseAttachment.objects.create(
        missive=missive,
        attachment_type=MissiveAttachmentType.VIRTUAL_ATTACHMENT,
        attachment_content_type=ContentType.objects.get_for_model(PdfDocument),
        attachment_object_id=doc.pk,
        attachment_object_arguments={"method": "retrieve_attachment"},
        priority=1,
        linked=False,
    )

    att = missive.generate_first_document()

    virtual.refresh_from_db()
    assert virtual.attachment_type == MissiveAttachmentType.VIRTUAL_ATTACHMENT
    assert virtual.attachment_object_id == doc.pk
    # And the first_document is its own dedicated row.
    assert att.pk != virtual.pk
    assert att.priority == FIRST_DOCUMENT_PRIORITY


def test_ensure_first_document_skips_non_postal(settings):
    """Email missives don't get a first-document — ``ensure_first_document`` is a no-op."""
    settings.PYMISSIVE_DEFAULT_FIRST_DOCUMENT_PROCESSORS = [
        "tests.test_first_document_flow._record_renderer",
    ]
    missive = _make_email_missive()
    assert missive.ensure_first_document() is None
    assert (
        missive.to_missiveattachment.filter(
            attachment_type=MissiveAttachmentType.ATTACHMENT,
            priority=FIRST_DOCUMENT_PRIORITY,
        ).count()
        == 0
    )


def test_ensure_first_document_swallows_processor_errors(settings):
    """Errors raised by the chain (e.g. missing libs) must not crash preview.

    The error is logged with a full traceback and ``None`` is returned so
    callers (the postal preview view) keep rendering.
    """
    settings.PYMISSIVE_DEFAULT_FIRST_DOCUMENT_PROCESSORS = [
        "tests.test_first_document_flow._broken_renderer",
    ]
    missive = _make_lre_missive()
    assert missive.ensure_first_document() is None


def _broken_renderer(*args, **kwargs):
    raise RuntimeError("boom — exercised by test_ensure_first_document_swallows_processor_errors")


# ---------------------------------------------------------------------------
# duplicate_missive — attachments + virtuals, but not first_document
# ---------------------------------------------------------------------------


def test_duplicate_missive_copies_regular_and_virtual_attachments(settings):
    """Regular AND virtual attachments are duplicated; first_document is excluded."""
    settings.PYMISSIVE_DEFAULT_FIRST_DOCUMENT_PROCESSORS = [
        "tests.test_first_document_flow._record_renderer",
    ]
    settings.PYMISSIVE_DEFAULT_ATTACHMENT_PROCESSORS = []  # avoid watermark side effects

    source = _make_lre_missive()
    regular = _attach_pdf(source, name="brief.pdf")
    doc = PdfDocument.objects.create(name="virtual.pdf")
    virtual = _attach_virtual_pdf(source, doc)
    first_doc = source.generate_first_document()  # priority 0

    new_missive = source.duplicate_missive(thread_type=MissiveThreadType.MISSIVE)
    new_attachments = new_missive.to_missiveattachment.all().order_by("priority")

    types = sorted(att.attachment_type for att in new_attachments)
    assert MissiveAttachmentType.ATTACHMENT in types
    assert MissiveAttachmentType.VIRTUAL_ATTACHMENT in types
    # First-document is NOT duplicated (will be regenerated on demand).
    assert all(
        att.priority != FIRST_DOCUMENT_PRIORITY or att.attachment_type != MissiveAttachmentType.ATTACHMENT
        for att in new_attachments
    )
    assert new_attachments.count() == 2  # regular + virtual

    # Virtual reference is preserved (same target object).
    duplicated_virtual = new_attachments.filter(
        attachment_type=MissiveAttachmentType.VIRTUAL_ATTACHMENT
    ).first()
    assert duplicated_virtual.attachment_object_id == doc.pk
    assert duplicated_virtual.attachment_content_type == virtual.attachment_content_type
    assert duplicated_virtual.pk != virtual.pk


def test_duplicate_missive_assigns_fresh_priorities(settings):
    """Duplicated attachments are renumbered starting at priority 1."""
    settings.PYMISSIVE_DEFAULT_ATTACHMENT_PROCESSORS = []
    source = _make_email_missive()
    _attach_pdf(source, name="a.pdf")
    _attach_pdf(source, name="b.pdf")

    new_missive = source.duplicate_missive(thread_type=MissiveThreadType.MISSIVE)
    priorities = sorted(att.priority for att in new_missive.to_missiveattachment.all())
    assert priorities == [1, 2]


# ---------------------------------------------------------------------------
# get_serialized_attachment + processor chain
# ---------------------------------------------------------------------------


def test_get_serialized_attachment_runs_chain(settings):
    """The bytes returned by ``get_serialized_attachment`` go through the chain."""
    _attachment_calls.clear()
    settings.PYMISSIVE_DEFAULT_ATTACHMENT_PROCESSORS = [
        "tests.test_first_document_flow._capturing_attachment_processor",
    ]
    missive = _make_email_missive()
    att = _attach_pdf(missive, name="x.pdf", content=b"hello")

    payload = att.get_serialized_attachment(linked=False)

    assert payload["content"] == b"hello + processed"
    assert len(_attachment_calls) == 1
    assert _attachment_calls[0]["attachment_pk"] == att.pk
    assert _attachment_calls[0]["is_first_document"] is False


def test_get_serialized_attachment_skips_chain_for_first_document(settings):
    """``first_document`` rows must NOT go through the attachment chain
    (they have their own ``first_document_processors`` chain).
    """
    _attachment_calls.clear()
    settings.PYMISSIVE_DEFAULT_FIRST_DOCUMENT_PROCESSORS = [
        "tests.test_first_document_flow._record_renderer",
    ]
    settings.PYMISSIVE_DEFAULT_ATTACHMENT_PROCESSORS = [
        "tests.test_first_document_flow._capturing_attachment_processor",
    ]
    missive = _make_lre_missive()
    first_doc = missive.generate_first_document()
    assert first_doc.is_first_document is True

    payload = first_doc.get_serialized_attachment(linked=False)

    assert payload["content"] == b"%PDF-FIRST-DOC"  # untouched
    assert _attachment_calls == []


def test_get_serialized_attachment_passthrough_when_chain_empty(settings):
    settings.PYMISSIVE_DEFAULT_ATTACHMENT_PROCESSORS = []
    missive = _make_email_missive()
    att = _attach_pdf(missive, name="x.pdf", content=b"raw bytes")

    payload = att.get_serialized_attachment(linked=False)
    assert payload["content"] == b"raw bytes"


def test_get_serialized_attachment_linked_skips_chain(settings):
    """``linked=True`` returns metadata only — no read, no chain run."""
    _attachment_calls.clear()
    settings.PYMISSIVE_DEFAULT_ATTACHMENT_PROCESSORS = [
        "tests.test_first_document_flow._capturing_attachment_processor",
    ]
    missive = _make_email_missive()
    att = _attach_pdf(missive, name="x.pdf", content=b"raw")

    payload = att.get_serialized_attachment(linked=True)

    assert "content" not in payload
    assert _attachment_calls == []


# ---------------------------------------------------------------------------
# is_pdf — works for both regular and virtual attachments
# ---------------------------------------------------------------------------


def test_is_pdf_for_regular_attachment(settings):
    settings.PYMISSIVE_DEFAULT_ATTACHMENT_PROCESSORS = []
    missive = _make_email_missive()
    pdf_att = _attach_pdf(missive, name="report.pdf")
    txt_att = MissiveBaseAttachment.objects.create(
        missive=missive,
        attachment_type=MissiveAttachmentType.ATTACHMENT,
        attachment_file=ContentFile(b"plain", name="notes.txt"),
        linked=False,
    )
    assert pdf_att.is_pdf is True
    assert txt_att.is_pdf is False


def test_is_pdf_for_virtual_attachment(settings, tmp_path):
    """Virtual attachments report ``is_pdf=True`` when the underlying handle
    points at a ``.pdf`` file. The fakeapp helper opens
    ``tests/pdf_sample_1mb.pdf`` by default, so we override the path to a
    minimal file we control to keep the test hermetic."""
    settings.PYMISSIVE_DEFAULT_ATTACHMENT_PROCESSORS = []
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 minimal")

    missive = _make_email_missive()
    doc = PdfDocument.objects.create(name="virt", fixture_path=str(pdf_path))
    virtual = _attach_virtual_pdf(missive, doc)

    assert virtual.is_pdf is True
    assert virtual.filename == "doc.pdf"


def test_is_pdf_for_virtual_attachment_with_non_pdf_extension(settings, tmp_path):
    """Virtual attachment pointing at a non-PDF reports ``is_pdf=False``."""
    settings.PYMISSIVE_DEFAULT_ATTACHMENT_PROCESSORS = []
    txt_path = tmp_path / "notes.txt"
    txt_path.write_bytes(b"plain")

    missive = _make_email_missive()
    doc = PdfDocument.objects.create(name="virt-text", fixture_path=str(txt_path))
    virtual = _attach_virtual_pdf(missive, doc)

    assert virtual.is_pdf is False


# ---------------------------------------------------------------------------
# watermark_pdf_attachments end-to-end (default chain in tests/settings.py)
# ---------------------------------------------------------------------------


def test_default_watermark_chain_stamps_pdf_attachments(small_pdf_bytes, settings):
    """The default chain configured in tests/settings.py wraps PDF
    attachments with a ``DRAFT`` watermark. Non-PDF attachments are
    untouched.
    """
    pytest.importorskip("pypdf")
    settings.PYMISSIVE_DEFAULT_ATTACHMENT_PROCESSORS = [
        [
            "django_pymissive.attachment_processors.watermark_pdf_attachments",
            {"text": "WATERMARK_SENTINEL", "alpha": 0.18},
        ],
    ]
    missive = _make_email_missive()
    pdf_att = _attach_pdf(missive, name="x.pdf", content=small_pdf_bytes)
    txt_att = MissiveBaseAttachment.objects.create(
        missive=missive,
        attachment_type=MissiveAttachmentType.ATTACHMENT,
        attachment_file=ContentFile(b"plain text", name="notes.txt"),
        linked=False,
    )

    pdf_payload = pdf_att.get_serialized_attachment(linked=False)
    txt_payload = txt_att.get_serialized_attachment(linked=False)

    assert pdf_payload["content"][:5] == b"%PDF-"
    assert pdf_payload["content"] != small_pdf_bytes  # mutated by watermark

    from pypdf import PdfReader

    reader = PdfReader(BytesIO(pdf_payload["content"]))
    assert any(
        "WATERMARK_SENTINEL" in (p.extract_text() or "") for p in reader.pages
    ), "Watermark should be visible on the PDF attachment"

    # Non-PDFs are untouched.
    assert txt_payload["content"] == b"plain text"
