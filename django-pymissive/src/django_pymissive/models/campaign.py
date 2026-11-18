"""Missive campaign models."""

import uuid

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models.deletion import ProtectedError
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from namedid import NamedIDField

from ..fields import JSONField, RichTextField
from ..managers.campaign import (
    MissiveCampaignManager,
    MissiveCampaignQuerySet,
    count_annotation_names,
    type_count_name,
)
from ..models.choices import (
    MissiveStatus,
    MissiveThreadType,
    sent_missive_q,
)
from ..models.mixins import CommentTimestampedModel, ConfigMixin, ProcessorsMixin
from ..utils import (
    json_safe,
    serialize_model_for_context,
    snapshot_html_read_more,
)


def _step_spec(spec) -> tuple[str, str, int]:
    if isinstance(spec, dict):
        missive_type = spec.get("missive_type")
        label = spec.get("label") or ""
        position = spec.get("position")
    else:
        try:
            missive_type, label, position = spec
        except (TypeError, ValueError) as exc:
            raise ValueError("A step spec is (missive_type, label, position) or a mapping of those keys.") from exc
    if position is None:
        raise ValueError("A step spec needs a position.")
    return str(missive_type or ""), str(label or ""), int(position)


def _progress_by_step(campaign) -> list:
    """Per-step totals. Missives with no step stay in the type totals only."""
    from django.db.models import Count

    from .choices import error_missive_q
    from .missive import Missive

    rows = (
        Missive._base_manager.filter(
            campaign_step__campaign=campaign,
            thread_type=MissiveThreadType.MISSIVE,
            campaign_step__isnull=False,
        )
        .values(
            "campaign_step_id",
            "campaign_step__label",
            "campaign_step__position",
            "campaign_step__missive_type",
        )
        .annotate(
            total=Count("id"),
            sent=Count("id", filter=sent_missive_q()),
            error=Count("id", filter=error_missive_q()),
        )
        .order_by("campaign_step__position", "campaign_step_id")
    )
    steps = []
    for row in rows:
        total = row["total"]
        sent = row["sent"]
        steps.append(
            {
                "id": row["campaign_step_id"],
                "label": row["campaign_step__label"],
                "position": row["campaign_step__position"],
                "missive_type": row["campaign_step__missive_type"],
                "total": total,
                "sent": sent,
                "error": row["error"],
                "progress": round(sent / total * 100) if total else 0,
            }
        )
    return steps


def _live_type_status_rows(campaign_ids):
    """Live missives of these campaigns, grouped by type and status.

    ``_base_manager`` so a recipient or event join cannot multiply the rows.
    ``order_by()`` drops the model's default ordering, which would otherwise
    leak into the ``GROUP BY``.
    """
    from django.db.models import Count
    from pymissive.config import MISSIVE_TYPES

    from .missive import Missive

    return (
        Missive._base_manager.filter(
            campaign_step__campaign_id__in=list(campaign_ids),
            missive_type__in=MISSIVE_TYPES,
            thread_type=MissiveThreadType.MISSIVE,
        )
        .order_by()
        .values("campaign_step__campaign_id", "missive_type", "status")
        .annotate(n=Count("id"))
    )


def _status_counts_by_type(rows) -> dict[str, dict[str, int]]:
    """Build ``{missive_type: {status: count}}`` from grouped rows."""
    result: dict[str, dict[str, int]] = {}
    for row in rows:
        status = row["status"] or ""
        if status:
            result.setdefault(row["missive_type"], {})[status] = row["n"] or 0
    return result


SNAPSHOT_VERSION = 1


def campaign_from_snapshot(snapshot) -> dict:
    """Campaign dict stored on a run.

    Versioned snapshots keep it under ``campaign``. Older runs stored the
    flat campaign fields at the top level and stay readable.
    """
    if not isinstance(snapshot, dict):
        return {}
    if snapshot.get("version"):
        campaign = snapshot.get("campaign")
        return dict(campaign) if isinstance(campaign, dict) else {}
    return dict(snapshot)


def _campaign_run_payload(run):
    return {
        "id": run.id,
        "scheduled_send_date": run.scheduled_send_date.isoformat() if run.scheduled_send_date else None,
        "send_date": run.send_date.isoformat() if run.send_date else None,
        "ended_at": run.ended_at.isoformat() if run.ended_at else None,
        "status": run.run_status,
        "url": run.get_progress_path(),
    }


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
    named_id = NamedIDField(
        source_fields=["subject"],
        generator="django_pymissive.generators.campaign_named_id",
        max_length=255,
        verbose_name=_("Named ID"),
        help_text=_("Unique identifier generated from the campaign label"),
    )
    subject = models.TextField(
        verbose_name=_("Label"),
        help_text=_("Campaign label. The subject of each message lives on its step."),
    )
    description = RichTextField(
        blank=True,
        default="",
        verbose_name=_("Description"),
        help_text=_("Campaign description (optional)"),
    )
    description_snapshot_html = RichTextField(
        blank=True,
        default="",
        verbose_name=_("Description HTML snapshot"),
        help_text=_("Optional rendered HTML snapshot of the campaign description"),
    )

    build_target_processors = JSONField(
        default=list,
        blank=True,
        verbose_name=_("Build target processors"),
        help_text=_(
            "Default chain that builds a target's missive. A scheduled run "
            "with an empty chain copies this list when it is saved. A target "
            "or a run with its own chain replaces it. Each entry may be a "
            "dotted path, a [path, kwargs] pair, or a "
            '{"processor": path, "kwargs": {...}} dict.'
        ),
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

    @property
    def description_snapshot_html_read_more(self):
        return snapshot_html_read_more(self.description_snapshot_html)

    def to_snapshot(self) -> dict:
        """JSON-serializable copy of this campaign, frozen when a run starts.

        ``version`` distinguishes this shape from the older flat snapshots.
        ``campaign`` is the campaign row. ``steps`` is the ordered list of
        steps, each with its typed configuration and the ids of its files.
        The legacy ``processing`` metadata key is omitted because run state
        belongs to the scheduler.
        """
        data = serialize_model_for_context(self)
        metadata = dict(data.get("metadata") or {})
        metadata.pop("processing", None)
        data["metadata"] = metadata
        campaign = json_safe(data)
        steps = [step.to_snapshot() for step in self.to_campaignstep.order_by("position", "pk")]
        return {
            "version": SNAPSHOT_VERSION,
            "campaign": campaign,
            "steps": steps,
        }

    def clean(self):
        super().clean()
        self._validate_processor_paths("build_target_processors")

    def get_browser_preview_path(self, *, preview_kind: str = "email", brand: str = "", campaign_step=None) -> str:
        """Relative URL for the preview of this campaign (unauthenticated, see ``PreviewView``).

        ``preview_kind`` selects which template will be rendered server-side
        (email, sms, postal, branded). ``brand`` picks
        the branded template. Returns ``""`` for an unsaved campaign.
        """
        if not self.pk:
            return ""
        from ..services.preview import campaign_preview_query

        return reverse("django_pymissive:preview", args=["campaign", self.pk]) + campaign_preview_query(
            kind=preview_kind,
            brand=brand,
            campaign_step=campaign_step,
        )

    @property
    def attachments(self):
        """Campaign-level attachments (ATTACHMENT + VIRTUAL_ATTACHMENT)."""
        from django.db.models import Q

        from .choices import MissiveAttachmentType

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
            annotated = type(self)._default_manager.with_counts().filter(pk=self.pk).first()
            fields = self._count_fields()
            cache = {field: (getattr(annotated, field, 0) or 0) if annotated else 0 for field in fields}
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
            raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")
        return self._count(name)

    @property
    def current_scheduler_id(self):
        """Primary key of the open scheduler, or ``None`` when idle."""
        if "open_scheduler_id" in self.__dict__:
            return self.__dict__["open_scheduler_id"]
        cache = getattr(self, "_prefetched_objects_cache", None) or {}
        runs = cache.get("to_missivecampaignsend")
        if runs is not None:
            current = next((run.pk for run in runs if run.ended_at is None), None)
        else:
            current = (
                self.to_missivecampaignsend.filter(ended_at__isnull=True)
                .order_by("-created_at", "-pk")
                .values_list("pk", flat=True)
                .first()
            )
        self.__dict__["open_scheduler_id"] = current
        return current

    @property
    def has_open_run(self) -> bool:
        """Whether a scheduler has not reached ``ended_at`` yet."""
        return self.current_scheduler_id is not None

    @property
    def is_processing(self) -> bool:
        """True while a scheduler has not reached ``ended_at`` yet."""
        return self.current_scheduler_id is not None

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
            annotated = (
                self.missive_queryset()
                .filter(
                    sent_missive_q(),
                    thread_type=MissiveThreadType.MISSIVE,
                )
                .exists()
            )
            self.__dict__["has_sent_missives"] = annotated
        return not annotated

    def delete(self, using=None, keep_parents=False):
        if not self.can_remove:
            protected: set[models.Model] = set(
                self.missive_queryset().filter(
                    sent_missive_q(),
                    thread_type=MissiveThreadType.MISSIVE,
                )
            )
            if not protected:
                protected.add(self)
            raise ProtectedError(
                str(_("Cannot delete a campaign that has missives which left the draft state.")),
                protected,
            )
        # The cascade deletes runs without calling their own delete().
        sending = self.to_missivecampaignsend.sending()
        if sending:
            from .scheduler import SENDING_RUN_DELETE_MESSAGE

            raise ProtectedError(str(SENDING_RUN_DELETE_MESSAGE), set(sending))
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
        return self.missive_queryset().filter(
            status=MissiveStatus.DRAFT,
            thread_type=MissiveThreadType.MISSIVE,
        )

    def missive_queryset(self):
        """Missives whose step belongs to this campaign."""
        from .missive import Missive

        return Missive._base_manager.filter(campaign_step__campaign=self)

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
            models.Q(scheduler__isnull=True) | models.Q(scheduler__ended_at__isnull=False),
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

    def ensure_steps(self, specs) -> dict:
        """Create each missing step from *specs*. Existing types are kept.

        *specs* is a sequence of ``(missive_type, label, position)`` or of
        mappings with those keys. A type that already has a step is skipped,
        so calling this twice does not insert a second row. When the requested
        position is already taken, the next free position is used, walking
        upward from the highest position already stored. The result maps each
        missive type to the first step of that type, ordered by position.
        """
        from pymissive.config import normalize_missive_type

        from .campaign_step import CampaignStep

        if self.pk is None:
            raise ValueError("Save the campaign before creating steps.")
        parsed = [_step_spec(spec) for spec in specs]
        canonical_specs = []
        for missive_type, label, position in parsed:
            canonical = normalize_missive_type(missive_type)
            if not canonical:
                raise ValueError(f"Unknown missive type: {missive_type!r}")
            if position < 0:
                raise ValueError(f"Step position must be zero or more, got {position}.")
            canonical_specs.append((canonical, label, position))

        with transaction.atomic():
            locked = type(self).objects_plain.select_for_update().get(pk=self.pk)
            existing: dict = {}
            taken: set[int] = set()
            for step in locked.to_campaignstep.all():
                existing.setdefault(step.missive_type, step)
                taken.add(step.position)
            for missive_type, label, position in canonical_specs:
                if missive_type in existing:
                    continue
                while position in taken:
                    position += 1
                step = CampaignStep(
                    campaign=locked,
                    missive_type=missive_type,
                    label=label,
                    position=position,
                )
                step.save()
                existing[missive_type] = step
                taken.add(position)
        return existing

    def get_step(self, missive_type: str, *, require_unique: bool = True):
        """Return the step of *missive_type*.

        With ``require_unique``, more than one step of that type raises
        ``ValueError``. Otherwise the lowest ``position`` wins, then the
        primary key. A missing step raises ``ValueError``.
        """
        from pymissive.config import normalize_missive_type

        canonical = normalize_missive_type(missive_type)
        if not canonical:
            raise ValueError(f"Unknown missive type: {missive_type!r}")
        steps = list(self.to_campaignstep.filter(missive_type=canonical).order_by("position", "pk"))
        if not steps:
            raise ValueError(f"Campaign has no {canonical!r} step.")
        if require_unique and len(steps) > 1:
            raise ValueError(
                f"Campaign has {len(steps)} {canonical!r} steps. Pass require_unique=False to use the first."
            )
        return steps[0]

    def get_progress_path(self) -> str:
        """Relative URL for the live progress page of this campaign."""
        if not self.pk:
            return ""
        return reverse("django_pymissive:campaign_progress", args=[self.pk])

    def get_absolute_url(self):
        """Used by Django admin "View on site"."""
        return self.get_progress_path()

    @classmethod
    def prefetch_type_counts(cls, campaigns) -> None:
        """Fill the ``by_status`` part of :meth:`counts_by_type` in one query."""
        campaigns = [campaign for campaign in campaigns if getattr(campaign, "pk", None)]
        pending = [campaign for campaign in campaigns if "_type_status_rows" not in campaign.__dict__]
        if not pending:
            return
        grouped = {}
        for row in _live_type_status_rows(campaign.pk for campaign in pending):
            grouped.setdefault(row["campaign_step__campaign_id"], []).append(row)
        for campaign in pending:
            campaign.__dict__["_type_status_rows"] = grouped.get(campaign.pk, [])

    @classmethod
    def type_count_fields(cls) -> tuple[str, ...]:
        """The ``with_counts`` annotations consumed by :meth:`counts_by_type`."""
        from pymissive.config import MISSIVE_TYPES

        return tuple(
            type_count_name(kind, missive_type) for missive_type in MISSIVE_TYPES for kind in ("total", "sent", "error")
        )

    def counts_by_type(self, *, only_active=False) -> dict[str, dict]:
        """Per-type live breakdown, the campaign-wide counterpart of a run's.

        ``{missive_type: {"total", "sent", "error", "progress", "by_status"}}``.
        ``by_status`` is ``{status: count}`` for that type.

        Same live set as ``count_sent`` and ``count_error`` from
        ``with_counts()``: ``thread_type=MISSIVE`` only, so an archived attempt
        is not counted again next to the missive that replaced it, and a
        conversation message stays out. ``sent`` and ``error`` use those
        counters' status sets. A legacy empty status stays in ``total`` and in
        no status, which is why a status sum can sit below ``total``.

        Targets are not included. ``count_target_*`` already counts them.

        ``total``, ``sent`` and ``error`` read the annotations produced by
        ``with_counts()``. ``by_status`` uses one grouped query rather than one
        extra aggregate per type/status cell; :meth:`prefetch_type_counts`
        performs that query once for a list. ``only_active`` drops types, and
        statuses, whose count is zero.
        """
        from pymissive.config import MISSIVE_TYPES

        rows = self.__dict__.get("_type_status_rows")
        if rows is None:
            rows = list(_live_type_status_rows([self.pk]))
            self.__dict__["_type_status_rows"] = rows
        status_by_type = _status_counts_by_type(rows)
        result = {}
        for missive_type in MISSIVE_TYPES:
            total = self._count(type_count_name("total", missive_type))
            if only_active and not total:
                continue
            sent = self._count(type_count_name("sent", missive_type))
            statuses = status_by_type.get(missive_type, {})
            if not only_active:
                statuses = {status.value: statuses.get(status.value, 0) for status in MissiveStatus}
            result[missive_type] = {
                "total": total,
                "sent": sent,
                "error": self._count(type_count_name("error", missive_type)),
                "progress": round(sent / total * 100) if total else 0,
                "by_status": statuses,
            }
        return result

    def progress_payload(self) -> dict:
        """JSON-serializable progress snapshot for the campaign front page.

        Live sends only, like ``count_sent`` / ``count_error``: the ``HISTORY``
        rows a retry archived would otherwise count their failure twice — once
        as the archive, once as its replacement — and a conversation message
        would inflate the progress of a campaign it is not part of. ``total``
        therefore stays below ``count_missive``, which counts every thread.
        ``by_type`` is :meth:`counts_by_type`.
        """
        from pymissive.config import MISSIVE_TYPES

        total_count = sent_count = error_count = 0
        by_type = {}
        for missive_type, counts in self.counts_by_type(only_active=True).items():
            total_count += counts["total"]
            sent_count += counts["sent"]
            error_count += counts["error"]
            by_type[missive_type] = {
                "label": MISSIVE_TYPES.get(missive_type, missive_type),
                **counts,
            }
        by_step = _progress_by_step(self)

        progress = round(sent_count / total_count * 100) if total_count else 0
        is_processing = self.is_processing

        if is_processing:
            status = "running"
        elif total_count and not self.pending_send_queryset().exists():
            status = "completed"
        else:
            status = "pending"

        runs = [_campaign_run_payload(run) for run in self.to_missivecampaignsend.order_by("-created_at")[:10]]

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
            "by_step": by_step,
            "runs": runs,
        }

    def release_stale_processing(self) -> None:
        """End crashed runs and reopen their unsent ``PROCESSING`` missives.

        ``ended_at`` is only written in ``run_with_tracking``'s ``finally``.
        A SIGKILL leaves ``is_running`` true, so after the heartbeat timeout
        the run is finalized and no longer blocks a new scheduler.
        """
        from .missive import Missive

        for run in self.to_missivecampaignsend.filter(ended_at__isnull=True):
            if run.is_stale:
                run._finalize_run(str(_("Stale run: timed out waiting for a heartbeat.")))
        Missive.reclaim_stale_processing(campaign=self)

    def start_campaign(self):
        """Start the campaign.

        Pending selection rows are built into missives by this run before it
        sends, on every channel that still has one. A campaign with no pending
        target only sends the drafts it already has.
        """
        from .campaign_target import CampaignTarget
        from .scheduler import SELECTION_TASK

        with transaction.atomic():
            campaign = MissiveCampaign.objects_plain.select_for_update().get(pk=self.pk)
            campaign.release_stale_processing()
            if campaign.is_processing:
                raise ValidationError(_("Campaign is already being processed."))
            channels = list(
                CampaignTarget.objects.filter(campaign=campaign)
                .filter(CampaignTarget.active_q())
                .order_by()
                .values_list("campaign_step__missive_type", flat=True)
                .distinct()
            )
            scheduled = campaign.to_missivecampaignsend.create(
                campaign=campaign,
                scheduled_send_date=timezone.now(),
                external_task_backend=SELECTION_TASK if channels else "",
                additional_config={"missive_types": channels} if channels else {},
            )
            # Attach pending missives to this scheduler in bulk so the
            # live annotations (with_counts) can be derived from the FK.
            campaign.claimable_send_queryset().update(scheduler=scheduled)
            scheduled.start_scheduled_campaign()
            return scheduled
