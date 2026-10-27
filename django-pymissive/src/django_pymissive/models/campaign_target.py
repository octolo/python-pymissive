"""Pending campaign targets, one row per (campaign, object, missive type).

A selection row is the checkbox: "this object must receive the campaign on
this channel". The missive is built later, one row at a time, by
:func:`django_pymissive.services.drafts.materialize_missive`.

For 1500 targets on one channel, preparing drafts up front writes 1500
``Missive``, as many ``MissiveRecipient``, 1500 ``MissiveRelatedObject``,
plus whatever rendering the project does. ``CampaignTarget`` replaces that
prepare step with one ``bulk_create``. After the send the row stays, so the
history of who was selected remains; the checkbox only reads rows that
still have no missive and are not abandoned, which is what lets the same
target be checked again.
"""

from __future__ import annotations

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from ..fields import JSONField
from ..managers.related_object import object_id_value
from ..utils import validate_import_paths
from .choices import MissiveStatus, MissiveType


def _target_slot(row):
    return (row.campaign_id, row.content_type_id, row.object_id, row.missive_type)


def _partition_deleted_targets(rows, drafts, taken):
    released, dropped = [], []
    for row in rows:
        key = _target_slot(row)
        if row.missive_id in drafts and key not in taken:
            taken.add(key)
            released.append(row)
        else:
            dropped.append(row)
    return released, dropped


def release_or_delete_target(collector, field, sub_objs, using):
    """``on_delete`` of :attr:`CampaignTarget.missive`.

    A deleted draft gives the checkbox back: its row loses the missive and
    is selected again, unless another live row already holds that slot. A
    deleted missive that left draft takes its row along, so a target that
    was sent is never queued again in silence.
    """
    from .missive import Missive

    rows = list(sub_objs)
    if not rows:
        return
    drafts = set(
        Missive._base_manager.using(using)
        .filter(pk__in={row.missive_id for row in rows}, status=MissiveStatus.DRAFT)
        .values_list("pk", flat=True)
    )
    taken = set(
        CampaignTarget._base_manager.using(using)
        .filter(
            CampaignTarget.active_q(),
            campaign_id__in={row.campaign_id for row in rows},
            content_type_id__in={row.content_type_id for row in rows},
            object_id__in={row.object_id for row in rows},
            missive_type__in={row.missive_type for row in rows},
        )
        .values_list("campaign_id", "content_type_id", "object_id", "missive_type")
    )
    released, dropped = _partition_deleted_targets(rows, drafts, taken)
    if released:
        models.SET_NULL(collector, field, released, using)
    if dropped:
        models.CASCADE(collector, field, dropped, using)


class CampaignTarget(models.Model):
    """One object retained for a campaign, on one missive type.

    ``missive_type`` is the channel (``email``, ``sms``, ``letter``, …).
    The business object is a generic link (``content_type`` + ``object_id``),
    so every project shares this table instead of subclassing it.

    The unique constraint covers only rows whose missive is still null.
    Once a send attaches a missive, a later selection can insert a new row
    for the same object and channel.
    """

    campaign = models.ForeignKey(
        "django_pymissive.MissiveCampaign",
        on_delete=models.CASCADE,
        related_name="to_campaigntarget",
        verbose_name=_("Campaign"),
    )
    missive_type = models.CharField(
        max_length=50,
        choices=MissiveType.choices,
        verbose_name=_("Missive type"),
        help_text=_("Channel this target is selected on (email, sms, letter, …)."),
    )
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        verbose_name=_("Content type"),
    )
    object_id = models.CharField(
        max_length=255,
        verbose_name=_("Object ID"),
        help_text=_("Primary key of the target (integer or UUID, stored as text)."),
    )
    target = GenericForeignKey("content_type", "object_id")
    object_str = models.CharField(
        max_length=500,
        blank=True,
        default="",
        editable=False,
        verbose_name=_("Object"),
        help_text=_("String form of the target, kept if the object is later deleted."),
    )
    # Denormalized pointer at the current missive. The full resend history
    # stays on MissiveRelatedObject; this column is what the checkbox and
    # the worker read without walking that generic link.
    missive = models.ForeignKey(
        "django_pymissive.Missive",
        on_delete=release_or_delete_target,
        null=True,
        blank=True,
        related_name="to_campaigntarget",
        verbose_name=_("Missive"),
    )
    build_target_processors = JSONField(
        default=list,
        blank=True,
        verbose_name=_("Build target processors"),
        help_text=_(
            "Processors that build this target's missive before it is sent. "
            "When non-empty, REPLACES the run, the campaign, and "
            "PYMISSIVE_DEFAULT_BUILD_TARGET_PROCESSORS. Each entry may be a dotted "
            "path, a [path, kwargs] pair, or a "
            '{"processor": path, "kwargs": {...}} dict. '
            "The first processor that returns a missive is used."
        ),
    )
    abandoned_at = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
        verbose_name=_("Abandoned at"),
        help_text=_(
            "Set when the target is given up without a missive. The row leaves the selection and stays as a trace."
        ),
    )
    abandon_reason = models.TextField(
        blank=True,
        default="",
        editable=False,
        verbose_name=_("Abandon reason"),
    )
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        verbose_name = _("Campaign target")
        verbose_name_plural = _("Campaign targets")
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["campaign", "missive_type"], name="campaigntarget_camp_type"),
            models.Index(fields=["content_type", "object_id"], name="campaigntarget_ct_oid"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["campaign", "content_type", "object_id", "missive_type"],
                condition=models.Q(missive__isnull=True, abandoned_at__isnull=True),
                name="uniq_campaigntarget_pending",
            ),
        ]

    def __str__(self):
        label = self.object_str or self.object_id or "?"
        return f"{label} — {self.missive_type}"

    def clean(self):
        super().clean()
        validate_import_paths(self, "build_target_processors")

    def _normalize_object_id(self) -> None:
        model = self.content_type.model_class()
        self.object_id = object_id_value(
            self.object_id,
            pk_field=model._meta.pk if model is not None else None,
        )

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        if self.object_id not in (None, "") and (update_fields is None or "object_id" in update_fields):
            self._normalize_object_id()
        if not self.object_str and (update_fields is None or "object_str" in update_fields):
            label = _label_from_target(self)
            if label:
                self.object_str = label
                if update_fields is not None and "object_str" not in update_fields:
                    kwargs["update_fields"] = [*update_fields, "object_str"]
        super().save(*args, **kwargs)

    @classmethod
    def active_q(cls):
        """Rows that still drive the checkbox: no missive attached yet, not abandoned."""
        return models.Q(missive__isnull=True, abandoned_at__isnull=True)

    def abandon(self, reason: str = "") -> bool:
        """Give this row up and keep it as a trace. False when it was no longer active."""
        now = timezone.now()
        updated = (
            type(self)
            ._base_manager.filter(pk=self.pk)
            .filter(self.active_q())
            .update(abandoned_at=now, abandon_reason=reason, updated_at=now)
        )
        if updated:
            self.abandoned_at = now
            self.abandon_reason = reason
        return bool(updated)

    def attach_missive(self, missive) -> None:
        """Point this row at *missive* so its status is readable in one join."""
        if self.missive_id == getattr(missive, "pk", None):
            return
        self.missive = missive
        self.save(update_fields=["missive", "updated_at"])

    def is_active(self) -> bool:
        """True while this row is the live checkbox (no missive yet, not abandoned)."""
        return not self.missive_id and not self.abandoned_at

    def history(self):
        """Every row of this target on this campaign and channel, newest first.

        A target checked again gets a new row; the older ones are its history.
        """
        return (
            type(self)
            .objects.filter(
                campaign_id=self.campaign_id,
                content_type_id=self.content_type_id,
                object_id=self.object_id,
                missive_type=self.missive_type,
            )
            .select_related("missive")
            .order_by("-created_at", "-id")
        )

    def thread_missives(self):
        """Every missive of this target's thread (sends, resends, retries), newest first.

        A resend keeps the thread of the previous missive, so one thread covers
        all the rows of :meth:`history`.
        """
        from .missive import Missive

        missive = self.missive
        thread_id = (
            missive.thread_id
            if missive is not None
            else self.history().filter(missive__isnull=False).values_list("missive__thread_id", flat=True).first()
        )
        if thread_id is None:
            return Missive.objects.none()
        return Missive.objects.filter(thread_id=thread_id).order_by("-created_at")


def resolve_build_target_processors(row=None, *, scheduler=None, campaign=None) -> list:
    """The chain that builds a target's missive; *row* may be ``None`` (no selection row).

    First one set wins: *row*'s, then *scheduler*'s, then the campaign's
    (*campaign*, or *row*'s), then
    ``settings.PYMISSIVE_DEFAULT_BUILD_TARGET_PROCESSORS``.
    """
    from ..processors.build_target import get_default_build_target_processors

    if campaign is None and row is not None:
        campaign = row.campaign
    for owner in (row, scheduler, campaign):
        processors = getattr(owner, "build_target_processors", None)
        if processors:
            return list(processors)
    return get_default_build_target_processors()


def _label_from_target(row: CampaignTarget) -> str:
    if not row.content_type_id or not row.object_id:
        return ""
    try:
        target = row.target
    except Exception:
        return ""
    if target is None:
        return ""
    try:
        return str(target)[:500]
    except Exception:
        return ""
