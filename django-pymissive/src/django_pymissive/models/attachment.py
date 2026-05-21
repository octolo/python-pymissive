"""MissiveAttachment model."""

import os
import uuid
from datetime import date

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.files.storage import Storage, default_storage
from django.db import models
from django.urls import reverse
from django.utils.deconstruct import deconstructible
from django.utils.module_loading import import_string
from django.utils.translation import gettext_lazy as _

from .mixins import CommentTimestampedModel
from .choices import MissiveAttachmentType
from ..utils import get_base_url
from ..managers.attachment import (
    MissiveBaseAttachmentManager,
    MissiveAttachmentManager,
    MissiveVirtualAttachmentManager,
    CampaignAttachmentManager,
    CampaignVirtualAttachmentManager,
    MissiveProofManager,
)
from ..fields import JSONField

# Priority 0 is reserved for the first-document (letter body PDF). Other attachments use 1, 2, 3...
FIRST_DOCUMENT_PRIORITY = 0


def _attachment_upload_to(instance, filename):
    """Return upload path based on attachment class."""
    upload_to = getattr(settings, 'PYMISSIVE_ATTACHMENT_UPLOAD_TO', None)
    if upload_to:
        return import_string(upload_to)(instance, filename)
    today = date.today()
    prefix = "campaign" if instance.campaign else "missive"
    attachment_type = instance.attachment_type.lower()
    uid = str(instance.pk)
    return f"pymissive/{prefix}/{attachment_type}/{uid}/{today:%Y/%m/%d}/{filename}"


def _get_attachment_file_storage():
    """Return storage for attachment_file. Configure via PYMISSIVE_ATTACHMENT_FILE_STORAGE.
    - None: use default_storage (MEDIA_ROOT)
    - str: import path to storage class, instantiated with ()
    - instance: use as-is (e.g. DataroomStorage())
    """
    storage = getattr(settings, 'PYMISSIVE_ATTACHMENT_FILE_STORAGE', None)
    if storage is None:
        return default_storage
    if isinstance(storage, str):
        storage_class = import_string(storage)
        return storage_class()
    return storage


@deconstructible
class ConfigurableAttachmentStorage(Storage):
    """Storage that delegates to PYMISSIVE_ATTACHMENT_FILE_STORAGE at runtime.
    Defined in django_pymissive to avoid migration dependency on project-specific storages.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._storage = None

    @property
    def _backend(self):
        if self._storage is None:
            self._storage = _get_attachment_file_storage()
        return self._storage

    def _open(self, name, mode='rb'):
        return self._backend._open(name, mode)

    def _save(self, name, content, max_length=None):
        # Override via PYMISSIVE_ATTACHMENT_PATH_MAX_LENGTH; cannot exceed field max_length.
        effective = getattr(settings, "PYMISSIVE_ATTACHMENT_PATH_MAX_LENGTH", None)
        if effective is not None:
            max_length = min(max_length or 2000, effective)
        try:
            return self._backend._save(name, content, max_length=max_length)
        except TypeError:
            return self._backend._save(name, content)

    def exists(self, name):
        return self._backend.exists(name)

    def delete(self, name):
        return self._backend.delete(name)

    def url(self, name):
        return self._backend.url(name)

    def size(self, name):
        return self._backend.size(name)

    def __getattr__(self, name):
        return getattr(self._backend, name)


class MissiveBaseAttachment(CommentTimestampedModel):
    """File attachment for missives or any other model."""

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        verbose_name=_("ID"),
    )

    campaign = models.ForeignKey(
        "django_pymissive.MissiveCampaign",
        on_delete=models.CASCADE,
        related_name="to_campaigndocument",
        verbose_name=_("Campaign"),
        null=True,
        blank=True,
        help_text=_("Campaign to which this file is attached"),
    )
    
    missive = models.ForeignKey(
        "django_pymissive.Missive",
        on_delete=models.CASCADE,
        related_name="to_missiveattachment",
        verbose_name=_("Missive"),
        null=True,
        blank=True,
        help_text=_("Missive to which this file is attached"),
    )

    attachment_type = models.CharField(
        max_length=50,
        choices=MissiveAttachmentType.choices,
        default=MissiveAttachmentType.ATTACHMENT,
        verbose_name=_("Attachment Type"),
        help_text=_("Type of attachment (attachment, signature, receipt, proof, other)"),
    )

    attachment_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        verbose_name=_("Object Type"),
        help_text=_("Type of model to which this file is attached"),
    )

    attachment_object_id = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name=_("Object ID"),
        help_text=_("ID of the object to which this file is attached"),
    )

    attachment_object_arguments = JSONField(
        default=dict({"method": "retrieve_attachment", "args": [], "kwargs": {}}),
        blank=True,
        verbose_name=_("Attachment Object Arguments"),
        help_text=_("Arguments to pass to the file method (as dict for **kwargs)"),
    )

    attachment_file = models.FileField(
        upload_to=_attachment_upload_to,
        storage=ConfigurableAttachmentStorage(),
        max_length=2000,
        blank=True,
        null=True,
        verbose_name=_("Attachment File"),
        help_text=_("Leave blank if the attachment is hosted externally"),
    )

    metadata = JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Metadata"),
        help_text=_("Additional metadata as JSON"),
    )

    linked = models.BooleanField(
        default=True,
        verbose_name=_("Linked"),
        help_text=_("Indicates if the attachment is linked to a related object"),
    )

    priority = models.PositiveIntegerField(
        default=1,
        verbose_name=_("Priority"),
        help_text=_("Page order. 0=first-document (letter body), others use 1, 2, 3... (0 reserved)"),
    )

    external_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name=_("External ID"),
        help_text=_("External ID of the attachment"),
    )

    page_count = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name=_("Page count"),
        help_text=_("Number of pages in the document"),
    )

    attachment_object = GenericForeignKey("attachment_content_type", "attachment_object_id")
    objects = MissiveBaseAttachmentManager()

    class Meta:
        verbose_name = _("Attachment")
        verbose_name_plural = _("Attachments")
        ordering = ["priority",]

    @property
    def is_first_document(self):
        """True if this is the first-document (letter body PDF). Reserved for priority 0."""
        name = getattr(self.attachment_file, "name", None) or ""
        return "first-document-" in name

    def _resolved_name(self) -> str:
        """Best-effort full path/name of the underlying file.

        For regular attachments this is the ``FieldFile`` name. For
        virtual attachments we have to peek at the helper's return value
        (typically an open binary handle) and immediately close it so we
        don't leak file descriptors. Returns ``""`` on any error so
        callers can degrade gracefully (no template crash on misconfigured
        virtual attachments).

        Cached on the instance so the preview loop can call ``filename``
        / ``is_pdf`` / ``mime_type`` without re-opening the file each time.
        """
        cached = self.__dict__.get("_resolved_name_cache")
        if cached is not None:
            return cached
        name = ""
        if self.attachment_type == MissiveAttachmentType.VIRTUAL_ATTACHMENT:
            if self.can_access_document():
                try:
                    handle = self.get_virtual_attachment()
                except Exception:
                    handle = None
                if handle is not None:
                    try:
                        name = getattr(handle, "name", "") or ""
                    finally:
                        try:
                            handle.close()
                        except Exception:
                            pass
        else:
            name = getattr(self.attachment_file, "name", None) or ""
        self.__dict__["_resolved_name_cache"] = name
        return name

    @property
    def filename(self) -> str:
        """Basename of the underlying file (or empty string).

        Resolves through :meth:`_resolved_name` so virtual attachments
        report the file name from the linked object instead of the empty
        ``attachment_file``.
        """
        return os.path.basename(self._resolved_name())

    @property
    def mime_type(self) -> str:
        """Best-effort mime type guessed from the filename, ``""`` if unknown."""
        import mimetypes

        name = self._resolved_name()
        if not name:
            return ""
        ctype, _ = mimetypes.guess_type(name)
        return (ctype or "").lower()

    @property
    def is_pdf(self) -> bool:
        """True if this attachment is a PDF (by extension or mimetype).

        Works for virtual attachments too: peeks the underlying file's
        name via :meth:`_resolved_name`.
        """
        name = self._resolved_name()
        if name.lower().endswith(".pdf"):
            return True
        return self.mime_type == "application/pdf"

    @property
    def can_be_modified(self):
        if hasattr(self, "missive"):
            return self.missive.can_be_modified
        if hasattr(self, "campaign"):
            return self.campaign.can_be_modified
        return False

    def can_access_document(self):
        """Checks if the document can be accessed."""
        return all(
            [
                self.attachment_content_type,
                self.attachment_object_id,
                self.attachment_object_arguments,
            ]
        )

    def get_virtual_attachment(self):
        """Gets the virtual attachment by calling the configured method on the related object."""
        get_method = self.attachment_object_arguments["method"]
        args = self.attachment_object_arguments.get("args", [])
        kwargs = self.attachment_object_arguments.get("kwargs", {})
        return getattr(self.attachment_object, get_method)(*args, **kwargs)

    def get_attachment(self):
        """Returns the raw file or virtual attachment object."""
        if self.attachment_type == MissiveAttachmentType.VIRTUAL_ATTACHMENT:
            return self.get_virtual_attachment()
        return self.attachment_file

    @property
    def attachment_url(self):
        return self.get_serialized_attachment(linked=True, ignore_content=True)

    @property
    def attachment_download_url(self):
        """Relative download URL (no base_url) — safe for same-origin fetch in browser."""
        scope = "campaign" if self.campaign_id else "missive"
        return reverse("django_pymissive:missive_attachment_download", args=[scope, self.id])

    def get_serialized_attachment(self, linked=False, ignore_content=False):
        """Returns a serialized dict for this attachment.

        When ``linked`` is False and ``ignore_content`` is False the file
        bytes are read AND piped through the attachment processors chain
        configured on the parent missive/campaign (see
        :mod:`django_pymissive.processors.attachment`). PDF-only processors
        (e.g. watermarking) skip non-PDF attachments transparently.
        """
        attachment = self.get_attachment()
        name = getattr(attachment, "name", None) or "unnamed_attachment"
        scope = "campaign" if self.campaign_id else "missive"
        url = reverse("django_pymissive:missive_attachment_download", args=[scope, self.id])
        base_url = get_base_url(trailing_slash=False)
        data = {
            "id": str(self.id),
            "external_id": self.external_id,
            "priority": self.priority,
            "name": os.path.basename(name),
            "url": base_url + url,
        }
        if linked or ignore_content:
            return data
        if hasattr(attachment, "seek"):
            attachment.seek(0)
        content_bytes = attachment.read()
        data["content"] = self._apply_attachment_processors(content_bytes)
        return data

    def _apply_attachment_processors(self, content_bytes: bytes) -> bytes:
        """Run the attachment processors chain configured on missive/campaign.

        Resolves the chain via "most specific wins" (missive →
        missive.campaign → defaults, falling back to the campaign chain
        when this attachment is owned by a campaign rather than a missive)
        and returns the (possibly transformed) bytes. Empty chain ⇒
        passthrough.

        The first_document attachment is **skipped**: it has its own
        dedicated chain (``first_document_processors``) and we don't want
        a watermark configured in both chains to be applied twice.
        """
        if not content_bytes:
            return content_bytes
        if self.is_first_document:
            return content_bytes
        from ..processors.attachment import (
            apply_attachment_processors,
            resolve_attachment_processors_for,
        )

        processors = resolve_attachment_processors_for(self)
        if not processors:
            return content_bytes

        missive = self.missive if self.missive_id else None
        campaign = self.campaign if self.campaign_id else None
        if missive is not None and campaign is None and getattr(missive, "campaign_id", None):
            campaign = missive.campaign

        return apply_attachment_processors(
            missive,
            self,
            content_bytes,
            processors,
            campaign=campaign,
        )

    def calculate_priority(self):
        """Return next priority. First-document uses 0; others use 1, 2, 3... (0 is reserved)."""
        from django.db.models import Max

        if self.is_first_document:
            return FIRST_DOCUMENT_PRIORITY
        qs = MissiveBaseAttachment.objects
        if self.missive_id:
            qs = qs.filter(missive_id=self.missive_id)
        elif self.campaign_id:
            qs = qs.filter(campaign_id=self.campaign_id)
        else:
            return 1
        # Exclude first-documents (priority 0) from max; others start at 1
        qs = qs.exclude(priority=FIRST_DOCUMENT_PRIORITY)
        max_priority = qs.aggregate(Max("priority"))["priority__max"] or (FIRST_DOCUMENT_PRIORITY)
        return max(1, max_priority + 1)

    def _recalculate_sibling_priorities(self):
        """Reassign sequential priorities (1, 2, 3...) when one attachment's priority changed."""
        from ..utils import recalculate_attachment_priorities

        recalculate_attachment_priorities(missive_id=self.missive_id, campaign_id=self.campaign_id)

    def can_access_attachment(self):
        """Checks if the attachment can be accessed."""
        if self.attachment_type == MissiveAttachmentType.VIRTUAL_ATTACHMENT:
            return (self.attachment_object and self.attachment_object_arguments)
        return self.attachment_file and self.attachment_file.url

    def clean(self):
        """Extension check vs missive type (skip virtual, first_document, campaign-only)."""
        super().clean()
        if self.attachment_type == MissiveAttachmentType.VIRTUAL_ATTACHMENT:
            return
        if self.is_first_document:
            return
        if not self.missive_id:
            return
        from django.core.exceptions import ValidationError

        from ..utils import validate_attachment_for_missive_type

        filename = getattr(self.attachment_file, "name", "") or ""
        missive_type = getattr(self.missive, "missive_type", None)
        try:
            validate_attachment_for_missive_type(filename, missive_type)
        except ValidationError as exc:
            raise ValidationError({"attachment_file": exc.messages}) from exc

    def save(self, *args, **kwargs):
        """Auto priority on insert (use ``_state.adding``, not ``pk`` — UUID set at init)."""
        if self._state.adding and (self.missive_id or self.campaign_id):
            self.priority = self.calculate_priority()
        else:
            if self.is_first_document:
                self.priority = FIRST_DOCUMENT_PRIORITY
            elif self.priority == FIRST_DOCUMENT_PRIORITY:
                self.priority = 1
        super().save(*args, **kwargs)

class MissiveAttachment(MissiveBaseAttachment):
    """Attachment for missives."""

    objects = MissiveAttachmentManager()

    class Meta:
        proxy = True
        verbose_name = _("Attachment")
        verbose_name_plural = _("Attachments")


class MissiveVirtualAttachment(MissiveBaseAttachment):
    """Virtual attachment for missives."""

    objects = MissiveVirtualAttachmentManager()

    class Meta:
        proxy = True
        verbose_name = _("Virtual Attachment")
        verbose_name_plural = _("Virtual Attachments")


class CampaignAttachment(MissiveBaseAttachment):
    """Attachment for campaigns."""

    objects = CampaignAttachmentManager()

    class Meta:
        proxy = True
        verbose_name = _("Campaign Attachment")
        verbose_name_plural = _("Campaign Attachments")


class CampaignVirtualAttachment(MissiveBaseAttachment):
    """Virtual attachment for campaigns."""

    objects = CampaignVirtualAttachmentManager()

    class Meta:
        proxy = True
        verbose_name = _("Campaign Virtual Attachment")
        verbose_name_plural = _("Campaign Virtual Attachments")

class MissiveProof(MissiveBaseAttachment):
    """Proof for missives."""

    objects = MissiveProofManager()

    class Meta:
        proxy = True
        verbose_name = _("Proof")
        verbose_name_plural = _("Proofs")