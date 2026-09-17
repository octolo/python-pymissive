"""Missive campaign models."""

import json
import uuid

from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models, transaction
from django.db.models.deletion import ProtectedError
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from ..managers.campaign import (
    MissiveCampaignManager,
    MissiveCampaignQuerySet,
    count_annotation_names,
)
from ..models.mixins import CommentTimestampedModel, ConfigMixin, ProcessorsMixin
from ..models.choices import (
    AcknowledgementLevel,
    MissiveDeliveryMode,
    MissivePriority,
    MissiveStatus,
    MissiveThreadType,
    sent_missive_q,
)
from django_geoaddress.fields import GeoaddressField
from phonenumber_field.modelfields import PhoneNumberField
from ..fields import RichTextField
from ..utils import (
    CAMPAIGN_SENDER_NAME_FIELDS,
    SENDER_CONTACT_FIELDS,
    apply_default_sender_fields,
    serialize_model_for_context,
)


class MissiveCampaign(ConfigMixin, ProcessorsMixin, CommentTimestampedModel):
    """Campaign grouping missives for batch sending.

    Inherits :class:`~django_pymissive.models.mixins.ConfigMixin` (JSON
    ``additional_context`` / ``additional_config`` / ``metadata`` bags) and
    :class:`~django_pymissive.models.mixins.ProcessorsMixin` (body /
    first_document / attachment processor chains + their resolvers). The
    campaign acts as the "parent" tier in the missive cascade — see
    :meth:`Missive._parent_processors`.
    """
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        verbose_name=_("ID"),
    )
    subject = models.TextField(
        verbose_name=_("Subject"),
        help_text=_("Campaign subject"),
    )
    description = RichTextField(
        blank=True,
        default="",
        verbose_name=_("Description"),
        help_text=_("Campaign description (optional)"),
    )

    # Email
    acknowledgement_email = models.CharField(
        max_length=50,
        choices=AcknowledgementLevel.choices,
        default=AcknowledgementLevel.BASIC_DELIVERY,
        verbose_name=_("Acknowledgement Level"),
        help_text=_("Desired acknowledgement level for delivery proof"),
    )
    sender_email_name = models.CharField(
        max_length=255,
        verbose_name=_("Sender email name"),
        help_text=_("Campaign sender email name"),
        blank=True,
        null=True,
    )
    sender_email = models.EmailField(
        verbose_name=_("Sender email"),
        help_text=_("Campaign sender email"),
        blank=True,
        null=True,
    )
    reply_to_email_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name=_("Reply-To name"),
        help_text=_("Display name for reply-to address"),
    )
    reply_to_email = models.EmailField(
        blank=True,
        null=True,
        verbose_name=_("Reply-To email"),
        help_text=_("Email address for replies"),
    )
    email_body_rich = RichTextField(
        blank=True,
        verbose_name=_("Email rich body"),
        help_text=_("Rich content body for email (HTML, RTF, …)"),
    )
    email_body_text = models.TextField(
        blank=True,
        verbose_name=_("Email plain text body"),
        help_text=_("Plain text body for email"),
    )

    # SMS / App
    sender_phone_name = models.CharField(
        max_length=255,
        verbose_name=_("Sender phone name"),
        help_text=_("Campaign sender phone name"),
        blank=True,
        null=True,
    )
    sender_phone = PhoneNumberField(
        blank=True,
        null=True,
        verbose_name=_("Sender phone"),
        help_text=_("Phone number of the sender (used for SMS)"),
    )
    phone_body_text = models.TextField(
        blank=True,
        verbose_name=_("SMS / App plain text body"),
        help_text=_("Plain text body for SMS, push and messaging apps"),
    )
    phone_body_rich = models.TextField(
        blank=True,
        verbose_name=_("SMS / App rich body"),
        help_text=_("Rich body for rich SMS, WhatsApp, RCS, etc."),
    )

    # Address / letter
    sender_address_name = models.CharField(
        max_length=255,
        verbose_name=_("Sender address name"),
        help_text=_("Campaign sender address name"),
        blank=True,
        null=True,
    )
    sender_address = GeoaddressField(
        verbose_name=_("Sender address"),
        help_text=_("Campaign sender address"),
        blank=True,
        null=True,
    )
    reply_to_address_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name=_("Reply-To address name"),
        help_text=_("Display name for reply-to address"),
    )
    reply_to_address = GeoaddressField(
        max_length=512,
        blank=True,
        null=True,
        verbose_name=_("Reply-To address"),
        help_text=_("Postal address for replies"),
    )
    acknowledgement_letter = models.CharField(
        max_length=50,
        choices=AcknowledgementLevel.choices,
        default=AcknowledgementLevel.BASIC_DELIVERY,
        verbose_name=_("Acknowledgement Level"),
        help_text=_("Desired acknowledgement level for delivery proof"),
    )
    delivery_mode_letter = models.CharField(
        max_length=50,
        choices=MissiveDeliveryMode.choices,
        default=MissiveDeliveryMode.NORMAL,
        verbose_name=_("Delivery Mode"),
        help_text=_("Delivery mode (economic, normal, premium, express)"),
    )
    priority_letter = models.CharField(
        max_length=20,
        choices=MissivePriority.choices,
        default=MissivePriority.NORMAL,
        verbose_name=_("Priority"),
        help_text=_("Priority level"),
    )
    duplex_printing_letter = models.BooleanField(
        default=True,
        verbose_name=_("Duplex printing"),
        help_text=_("Print the letter on both sides (recto verso)"),
    )
    color_printing_letter = models.BooleanField(
        default=False,
        verbose_name=_("Color printing"),
        help_text=_("Print the letter in color"),
    )
    first_document = RichTextField(
        blank=True,
        verbose_name=_("First Document"),
        help_text=_("First document content (HTML, converted to PDF for postal letters)"),
    )

    objects = MissiveCampaignManager()
    # Same queryset (so ``delete()`` is protected) but no default annotations —
    # PostgreSQL rejects ``FOR UPDATE`` with those extra columns / GROUP BY.
    objects_plain = MissiveCampaignQuerySet.as_manager()

    class Meta:
        verbose_name = _("Campaign")
        verbose_name_plural = _("Campaigns")
        ordering = ["-created_at", "subject"]

    def __str__(self):
        return self.subject

    def to_snapshot(self) -> dict:
        """JSON-serializable copy of this campaign's configuration.

        Used by a scheduled run to freeze the campaign at send start, so later
        edits do not rewrite the history of that run. The live ``processing``
        metadata flag is omitted: it is a lock, not configuration.
        """
        data = serialize_model_for_context(self)
        metadata = dict(data.get("metadata") or {})
        metadata.pop("processing", None)
        data["metadata"] = metadata
        return json.loads(json.dumps(data, cls=DjangoJSONEncoder, default=str))

    def _ensure_default_sender(self):
        """Fill every empty sender slot from ``PYMISSIVE_DEFAULT_SENDER``."""
        fields = {attr: "name" for attr in CAMPAIGN_SENDER_NAME_FIELDS}
        for attr, key in SENDER_CONTACT_FIELDS.values():
            fields[attr] = key
        apply_default_sender_fields(self, fields)

    def save(self, *args, **kwargs):
        self._ensure_default_sender()
        super().save(*args, **kwargs)

    def get_browser_preview_path(self, *, preview_kind: str = "email") -> str:
        """Relative URL for the preview of this campaign (unauthenticated, see ``PreviewView``).

        ``preview_kind`` selects which template will be rendered server-side
        (email, sms, postal). Returns ``""`` for an unsaved campaign.
        """
        if not self.pk:
            return ""
        return (
            reverse("django_pymissive:preview", args=["campaign", self.pk])
            + f"?type={preview_kind}"
        )

    @property
    def email_reply_to(self):
        """Reply-to dict for email; None when no reply address."""
        if not self.reply_to_email:
            return None
        return {
            "name": self.reply_to_email_name or "",
            "email": str(self.reply_to_email),
        }

    @property
    def address_reply_to(self):
        return {
            "name": self.reply_to_address_name or "",
            "address": self.reply_to_address or "",
        }

    @property
    def phone_sender(self):
        return {
            "name": self.sender_phone_name or "",
            "phone": self.sender_phone or "",
        }

    @property
    def email_sender(self):
        return {
            "name": self.sender_email_name or "",
            "email": self.sender_email or "",
        }

    @property
    def address_sender(self):
        return {
            "name": self.sender_address_name or "",
            "address": self.sender_address or "",
        }

    @property
    def attachments(self):
        """Campaign-level attachments (ATTACHMENT + VIRTUAL_ATTACHMENT)."""
        from .choices import MissiveAttachmentType
        from django.db.models import Q
        return self.to_campaigndocument.filter(
            Q(attachment_type=MissiveAttachmentType.ATTACHMENT)
            | Q(attachment_type=MissiveAttachmentType.VIRTUAL_ATTACHMENT),
        )

    # ------------------------------------------------------------------
    # Counters (annotated by with_counts(), fetched on demand otherwise)
    # ------------------------------------------------------------------

    @classmethod
    def _count_fields(cls) -> frozenset:
        """Every counter name ``with_counts()`` produces — read from its source.

        Derived rather than listed again: a counter added to
        :func:`~django_pymissive.managers.campaign.count_annotations` becomes
        readable on a non-annotated campaign at the same time.
        """
        return count_annotation_names()

    def _count(self, name: str):
        """One counter, from the annotation when present, from the database else.

        The whole set is fetched and cached in one query, so reading a second
        counter on the same instance is free.
        """
        if name in self.__dict__:
            return self.__dict__[name] or 0
        cache = self.__dict__.get("_counts_cache")
        if cache is None:
            annotated = (
                type(self)._default_manager.with_counts().filter(pk=self.pk).first()
            )
            fields = self._count_fields()
            cache = {
                field: (getattr(annotated, field, 0) or 0) if annotated else 0
                for field in fields
            }
            self.__dict__["_counts_cache"] = cache
        return cache.get(name, 0)

    def __getattr__(self, name):
        """Serve a counter of ``with_counts()`` the queryset did not annotate.

        The counters are opt-in — they force a ``GROUP BY`` that every plain
        lookup would otherwise pay — but a template or a report reading
        ``campaign.count_missive`` must keep working. It costs one query per
        campaign, so annotate with ``with_counts()`` when a list displays them.
        """
        # Prefix first: this runs on every missing attribute, and Django probes a
        # few (``get_absolute_url``, dunders), which have no business building the
        # annotation set.
        if not name.startswith(("count_", "pct_")) or name not in self._count_fields():
            raise AttributeError(
                f"{type(self).__name__!r} object has no attribute {name!r}"
            )
        return self._count(name)

    @property
    def is_processing(self) -> bool:
        """True while a send is under way.

        Either ``start_campaign`` flagged the campaign, or a scheduled run has
        not ended yet. Reads the ``has_open_run`` annotation or the prefetch
        cache of ``to_missivecampaignsend`` when either is available, so
        iterating a list of campaigns costs no query per row.

        The fallback ``EXISTS`` is memoised under the annotation name, so reading
        the property twice on an instance that carries neither — a campaign
        reached through ``select_related("campaign")`` from a missive — queries
        once, not twice. Like the annotation itself, it is a snapshot: reload the
        campaign after starting a send.
        """
        if (self.metadata or {}).get("processing"):
            return True
        annotated = getattr(self, "has_open_run", None)
        if annotated is not None:
            return bool(annotated)
        cache = getattr(self, "_prefetched_objects_cache", None) or {}
        runs = cache.get("to_missivecampaignsend")
        if runs is not None:
            return any(run.ended_at is None for run in runs)
        open_run = self.to_missivecampaignsend.filter(ended_at__isnull=True).exists()
        self.__dict__["has_open_run"] = open_run
        return open_run

    @property
    def can_remove(self) -> bool:
        """True while no live missive of the campaign has left the draft state.

        Enforced by :meth:`delete` and the campaign queryset. Uses the
        ``has_sent_missives`` annotation when the queryset carries it
        (``MissiveCampaignManager`` adds it by default), else falls back to a
        single ``EXISTS``, memoised under the annotation name like
        :pyattr:`is_processing` does.
        """
        annotated = getattr(self, "has_sent_missives", None)
        if annotated is None:
            annotated = self.to_missive.filter(
                sent_missive_q(), thread_type=MissiveThreadType.MISSIVE,
            ).exists()
            self.__dict__["has_sent_missives"] = annotated
        return not annotated

    def delete(self, using=None, keep_parents=False):
        if not self.can_remove:
            protected = set(
                self.to_missive.filter(
                    sent_missive_q(), thread_type=MissiveThreadType.MISSIVE,
                )
            )
            raise ProtectedError(
                _("Cannot delete a campaign that has missives which left the draft state."),
                protected or {self},
            )
        return super().delete(using=using, keep_parents=keep_parents)

    def pending_send_queryset(self):
        """The missives a send would push out right now.

        The single definition of that set: :meth:`start_campaign` and the run
        (``run_with_tracking`` / ``get_missives``) all derive from it, whatever
        run the drafts were attached to.

        ``thread_type`` matters as much as the status here. A conversation
        message lives in the same table with the same ``draft`` default, so
        without that filter a reply being composed would be claimed by the next
        campaign send and pushed out.

        Deliberately narrower than :func:`pending_missive_q` on the status side:
        the send pipeline transitions ``draft`` rows to ``processing``, so legacy
        rows with an empty status are counted as pending by the campaign
        annotations but are never actually sent.
        """
        return self.to_missive.filter(
            status=MissiveStatus.DRAFT,
            thread_type=MissiveThreadType.MISSIVE,
        )

    def claimable_send_queryset(self):
        """The pending missives a *new* run may take over.

        Same set as :meth:`pending_send_queryset` minus the drafts another run is
        still working on. A draft duplicated by ``retry_failed`` keeps the FK of
        the run that produced it, so restricting to ``scheduler IS NULL`` would
        leave it stranded once that run has ended; a run still open, on the other
        hand, reads its own scope through that same FK and must be left alone.

        Used by :meth:`start_campaign` and by the run itself
        (``run_with_tracking`` / ``get_missives``), so that a run created by hand
        claims exactly what a run created here would.
        """
        return self.pending_send_queryset().filter(
            models.Q(scheduler__isnull=True)
            | models.Q(scheduler__ended_at__isnull=False),
        )

    def send_preview_payload(self) -> dict:
        """What :meth:`start_campaign` would send, grouped by support and by type.

        The counterpart of :meth:`progress_payload` for the confirmation step
        shown *before* sending. ``by_support`` uses the canonical support keys
        (``email``, ``phone``, ``address``, ``application``) so a caller never
        has to know which types belong to which channel.
        """
        from pymissive.config import GENERIC_SUPPORT, missive_support_for_type

        by_support = dict.fromkeys(GENERIC_SUPPORT, 0)
        by_type: dict = {}
        total = 0
        rows = (
            self.pending_send_queryset()
            .order_by()
            .values("missive_type")
            .annotate(total=models.Count("id", distinct=True))
        )
        for row in rows:
            count = row["total"]
            total += count
            by_type[row["missive_type"]] = count
            support = missive_support_for_type(row["missive_type"])
            if support:
                by_support[support] += count
        return {"total": total, "by_support": by_support, "by_type": by_type}

    def get_progress_path(self) -> str:
        """Relative URL for the live progress page of this campaign."""
        if not self.pk:
            return ""
        return reverse("django_pymissive:campaign_progress", args=[self.pk])

    def get_absolute_url(self):
        """Used by Django admin "View on site"."""
        return self.get_progress_path()

    def progress_payload(self) -> dict:
        """JSON-serializable progress snapshot for the campaign front page.

        Live sends only, like ``count_sent`` / ``count_error``: the ``HISTORY``
        rows a retry archived would otherwise count their failure twice — once
        as the archive, once as its replacement — and a conversation message
        would inflate the progress of a campaign it is not part of. ``total``
        therefore stays below ``count_missive``, which counts every thread.
        """
        from django.db.models import Count
        from pymissive.config import MISSIVE_TYPES
        from ..models.choices import error_missive_q
        from ..models.missive import Missive

        # _base_manager rather than self.to_missive: the default manager annotates
        # counts over reverse FKs, and their LEFT JOINs survive .values() — which
        # only drops the column — so each Count would group multiplied rows and
        # inflate the progress by recipients x events.
        rows = (
            Missive._base_manager
            .filter(campaign=self, thread_type=MissiveThreadType.MISSIVE)
            .values("missive_type")
            .annotate(
                total=Count("id"),
                sent=Count("id", filter=sent_missive_q()),
                error=Count("id", filter=error_missive_q()),
            )
        )

        by_type: dict = {}
        total_count = sent_count = error_count = 0

        for row in rows:
            mtype = row["missive_type"]
            total = row["total"]
            sent = row["sent"]
            error = row["error"]
            total_count += total
            sent_count += sent
            error_count += error
            by_type[mtype] = {
                "label": MISSIVE_TYPES.get(mtype, mtype),
                "total": total,
                "sent": sent,
                "error": error,
                "progress": round(sent / total * 100) if total else 0,
            }

        progress = round(sent_count / total_count * 100) if total_count else 0
        is_processing = self.is_processing

        if is_processing:
            status = "running"
        elif total_count and not self.pending_send_queryset().exists():
            status = "completed"
        else:
            status = "pending"

        runs = []
        for run in self.to_missivecampaignsend.order_by("-created_at")[:10]:
            runs.append({
                "id": run.id,
                "scheduled_send_date": (
                    run.scheduled_send_date.isoformat() if run.scheduled_send_date else None
                ),
                "send_date": run.send_date.isoformat() if run.send_date else None,
                "ended_at": run.ended_at.isoformat() if run.ended_at else None,
                "status": run.run_status,
                "url": run.get_progress_path(),
            })

        return {
            "id": str(self.pk),
            "subject": self.subject,
            "running": is_processing,
            "status": status,
            "total_count": total_count,
            "sent_count": sent_count,
            "error_count": error_count,
            "progress": progress,
            "by_type": by_type,
            "runs": runs,
        }

    def release_stale_processing(self) -> None:
        """End crashed runs and reopen their unsent ``PROCESSING`` missives.

        ``ended_at`` is only written in ``run_with_tracking``'s ``finally``.
        A SIGKILL leaves ``is_running`` true and ``metadata['processing']``
        set, so the next ``start_campaign`` would raise forever. After the
        heartbeat timeout those runs are finalized and leftover flags cleared.
        """
        from .missive import Missive

        for run in self.to_missivecampaignsend.filter(ended_at__isnull=True):
            if run.is_stale:
                run._finalize_run(
                    str(_("Stale run: timed out waiting for a heartbeat."))
                )
        Missive.reclaim_stale_processing(campaign=self)
        still_open = self.to_missivecampaignsend.filter(ended_at__isnull=True).exists()
        if still_open:
            return
        if (self.metadata or {}).get("processing"):
            metadata = dict(self.metadata or {})
            metadata.pop("processing", None)
            self.metadata = metadata
            self.save(update_fields=["metadata"])

    def start_campaign(self):
        """Start the campaign."""
        with transaction.atomic():
            campaign = MissiveCampaign.objects_plain.select_for_update().get(pk=self.pk)
            campaign.release_stale_processing()
            if campaign.metadata.get("processing"):
                raise ValidationError(_("Campaign is already being processed."))
            campaign.metadata = {**dict(campaign.metadata), "processing": True}
            campaign.save(update_fields=["metadata"])
            scheduled = campaign.to_missivecampaignsend.create(
                campaign=campaign,
                scheduled_send_date=timezone.now()
            )
            # Attach pending missives to this scheduler in bulk so the
            # live annotations (with_counts) can be derived from the FK.
            campaign.claimable_send_queryset().update(scheduler=scheduled)
            scheduled.start_scheduled_campaign()
