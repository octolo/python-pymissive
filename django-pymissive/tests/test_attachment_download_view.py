"""Integration tests for ``MissiveAttachmentDownloadView``.

Covers the wiring between the download endpoint and the attachment
processor chain, for both regular and virtual attachments — and the
``?raw=1`` escape hatch that bypasses the chain entirely.
"""

from __future__ import annotations

from io import BytesIO

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.test import Client
from django.urls import reverse

from django_pymissive.models.attachment import MissiveBaseAttachment
from django_pymissive.models.choices import MissiveAttachmentType
from django_pymissive.models.missive import Missive
from tests.fakeapp.models import PdfDocument

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Reachable-by-dotted-path processor capture state.
# ---------------------------------------------------------------------------

_view_calls: list[dict] = []


def _stamp_with_marker(missive, attachment, content_bytes, **kwargs):
    """Attachment processor that prepends a sentinel for assertion."""
    _view_calls.append({
        "attachment_pk": attachment.pk,
        "is_first_document": attachment.is_first_document,
    })
    return b"STAMPED|" + (content_bytes or b"")


def _record_renderer(missive, pdf_bytes, **kwargs) -> bytes:
    return b"%PDF-FIRST-DOC"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_email_missive() -> Missive:
    return Missive.objects.create(
        missive_type="email",
        subject="Email",
        body_html="<p>hi</p>",
    )


def _make_lre_missive() -> Missive:
    return Missive.objects.create(
        missive_type="lre",
        subject="LRE",
        body_html="<p>letter body</p>",
    )


def _attach_pdf(missive, *, name="doc.pdf", content=b"raw payload"):
    return MissiveBaseAttachment.objects.create(
        missive=missive,
        attachment_type=MissiveAttachmentType.ATTACHMENT,
        attachment_file=ContentFile(content, name=name),
        linked=False,
    )


def _download(client: Client, attachment, *, raw: bool = False):
    url = reverse(
        "django_pymissive:missive_attachment_download",
        args=["missive", attachment.id],
    )
    if raw:
        url = f"{url}?raw=1"
    return client.get(url)


# ---------------------------------------------------------------------------
# Regular attachments
# ---------------------------------------------------------------------------


def test_download_regular_attachment_runs_chain(client, settings):
    _view_calls.clear()
    settings.PYMISSIVE_DEFAULT_ATTACHMENT_PROCESSORS = [
        "tests.test_attachment_download_view._stamp_with_marker",
    ]
    missive = _make_email_missive()
    att = _attach_pdf(missive, content=b"hello")

    response = _download(client, att)

    assert response.status_code == 200
    assert response.content == b"STAMPED|hello"
    assert _view_calls and _view_calls[0]["attachment_pk"] == att.pk


def test_download_with_raw_query_skips_chain(client, settings):
    _view_calls.clear()
    settings.PYMISSIVE_DEFAULT_ATTACHMENT_PROCESSORS = [
        "tests.test_attachment_download_view._stamp_with_marker",
    ]
    missive = _make_email_missive()
    att = _attach_pdf(missive, content=b"hello-raw")

    response = _download(client, att, raw=True)

    assert response.status_code == 200
    body = b"".join(response.streaming_content) if hasattr(response, "streaming_content") else response.content
    assert body == b"hello-raw"
    assert _view_calls == []


def test_download_first_document_skips_attachment_chain(client, settings):
    """Even though there's an attachment processor chain configured, the
    first_document is excluded — its bytes pass through unmodified."""
    _view_calls.clear()
    settings.PYMISSIVE_DEFAULT_FIRST_DOCUMENT_PROCESSORS = [
        "tests.test_attachment_download_view._record_renderer",
    ]
    settings.PYMISSIVE_DEFAULT_ATTACHMENT_PROCESSORS = [
        "tests.test_attachment_download_view._stamp_with_marker",
    ]
    missive = _make_lre_missive()
    first_doc = missive.generate_first_document()

    response = _download(client, first_doc)

    assert response.status_code == 200
    assert response.content == b"%PDF-FIRST-DOC"
    assert _view_calls == []


# ---------------------------------------------------------------------------
# Virtual attachments
# ---------------------------------------------------------------------------


def test_download_virtual_attachment_runs_chain(client, settings, tmp_path):
    """Regression: virtual attachments return a plain file handle (no
    ``FieldFile.open``); the view must still read its bytes and run them
    through the chain."""
    _view_calls.clear()
    settings.PYMISSIVE_DEFAULT_ATTACHMENT_PROCESSORS = [
        "tests.test_attachment_download_view._stamp_with_marker",
    ]
    pdf_path = tmp_path / "virtual.pdf"
    pdf_path.write_bytes(b"%PDF-virtual-bytes")

    missive = _make_email_missive()
    doc = PdfDocument.objects.create(name="virt", fixture_path=str(pdf_path))
    virtual = MissiveBaseAttachment.objects.create(
        missive=missive,
        attachment_type=MissiveAttachmentType.VIRTUAL_ATTACHMENT,
        attachment_content_type=ContentType.objects.get_for_model(PdfDocument),
        attachment_object_id=doc.pk,
        attachment_object_arguments={"method": "retrieve_attachment"},
        linked=False,
    )

    response = _download(client, virtual)

    assert response.status_code == 200
    assert response.content == b"STAMPED|%PDF-virtual-bytes"
    assert _view_calls and _view_calls[0]["attachment_pk"] == virtual.pk


def test_download_virtual_attachment_with_raw(client, settings, tmp_path):
    """``?raw=1`` returns the unprocessed file handle for a virtual attachment."""
    settings.PYMISSIVE_DEFAULT_ATTACHMENT_PROCESSORS = [
        "tests.test_attachment_download_view._stamp_with_marker",
    ]
    pdf_path = tmp_path / "virtual-raw.pdf"
    pdf_path.write_bytes(b"%PDF-virtual-raw")

    missive = _make_email_missive()
    doc = PdfDocument.objects.create(name="virt-raw", fixture_path=str(pdf_path))
    virtual = MissiveBaseAttachment.objects.create(
        missive=missive,
        attachment_type=MissiveAttachmentType.VIRTUAL_ATTACHMENT,
        attachment_content_type=ContentType.objects.get_for_model(PdfDocument),
        attachment_object_id=doc.pk,
        attachment_object_arguments={"method": "retrieve_attachment"},
        linked=False,
    )

    response = _download(client, virtual, raw=True)

    assert response.status_code == 200
    body = b"".join(response.streaming_content) if hasattr(response, "streaming_content") else response.content
    assert body == b"%PDF-virtual-raw"


def test_download_chain_failure_falls_back_to_raw_bytes(client, settings):
    """If a processor explodes the view logs a warning and serves the raw bytes
    so the user always gets the file (preview never blocked by a buggy hook).
    """
    settings.PYMISSIVE_DEFAULT_ATTACHMENT_PROCESSORS = [
        "tests.test_attachment_download_view._exploding_processor",
    ]
    missive = _make_email_missive()
    att = _attach_pdf(missive, content=b"safe-bytes")

    response = _download(client, att)
    assert response.status_code == 200
    assert response.content == b"safe-bytes"


def _exploding_processor(missive, attachment, content_bytes, **kwargs):
    raise RuntimeError("chain failure exercised by test")
