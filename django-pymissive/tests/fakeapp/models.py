"""Models for the fakeapp test app.

A minimal model that owns a fixture PDF and exposes it via a method
compatible with the ``MissiveBaseAttachment`` virtual attachment contract.

Wire it as a virtual attachment::

    from django.contrib.contenttypes.models import ContentType
    from django_pymissive.models.attachment import MissiveBaseAttachment
    from django_pymissive.models.choices import MissiveAttachmentType
    from tests.fakeapp.models import PdfDocument

    doc = PdfDocument.objects.create(name="sample")
    MissiveBaseAttachment.objects.create(
        missive=missive,
        attachment_type=MissiveAttachmentType.VIRTUAL_ATTACHMENT,
        attachment_content_type=ContentType.objects.get_for_model(PdfDocument),
        attachment_object_id=doc.pk,
        attachment_object_arguments={"method": "retrieve_attachment"},
        priority=1,
        linked=False,
    )

The attachment processor chain (notably :func:`watermark_pdf_attachments`)
runs against the bytes returned by :meth:`PdfDocument.retrieve_attachment`,
so this is the easiest way to manually test PDF watermarking on
attachments without uploading a real file.
"""

from pathlib import Path

from django.db import models

# tests/ folder (parent of fakeapp/), where ``pdf_sample_1mb.pdf`` lives.
FIXTURE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_FIXTURE = FIXTURE_DIR / "pdf_sample_1mb.pdf"


class PdfDocument(models.Model):
    """Fake business object that owns a PDF fixture file.

    Stores only a label; the actual bytes come from a file on disk so we
    don't have to upload anything to test the virtual attachment flow.
    Override the path per instance via :attr:`fixture_path` to point at a
    different file (e.g. ``personal-workspace/fixtures/pdf_sample_1mb.pdf``).
    """

    name = models.CharField(max_length=200, default="sample.pdf")
    published_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Optional publication date (used to test datetime serialization in context).",
    )
    fixture_path = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text=(
            "Optional absolute path to a PDF on disk. Defaults to "
            "tests/pdf_sample_1mb.pdf when blank."
        ),
    )

    class Meta:
        app_label = "fakeapp"
        verbose_name = "PDF document (test fixture)"

    def __str__(self) -> str:
        return self.name or f"PdfDocument#{self.pk}"

    def retrieve_attachment(self, path: str | None = None):
        """Return the fixture PDF as a binary file handle.

        Called by ``MissiveBaseAttachment.get_virtual_attachment`` when
        this instance is wired as the ``attachment_object`` with
        ``attachment_object_arguments = {"method": "retrieve_attachment"}``.

        The returned handle exposes ``name`` / ``seek`` / ``read`` so the
        existing serialization code reads its bytes (which then run
        through the configured ``attachment_processors`` chain).
        """
        target = Path(path or self.fixture_path or str(DEFAULT_FIXTURE))
        if not target.exists():
            raise FileNotFoundError(f"PDF fixture not found at {target}")
        return target.open("rb")

    def to_context_dict(self) -> dict:
        return {
            "display_name": self.name.upper(),
            "is_published": self.published_at is not None,
        }
