"""Missive scheduled campaign model."""

import logging
import uuid

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models.deletion import ProtectedError
from django.urls import reverse
from django.utils import timezone
from django.utils.module_loading import import_string
from django.utils.translation import gettext_lazy as _
from pymissive.config import MISSIVE_TYPES

from ..fields import JSONField
from ..managers.scheduler import (
    ATTEMPT_THREADS,
    ERROR_STATUSES,
    MissiveScheduledCampaignManager,
    count_annotations,
    error_annotation_name,
    sent_annotation_name,
    status_annotation_name,
    thread_annotation_name,
    total_annotation_name,
)
from ..models.choices import MissiveStatus, MissiveThreadType, MissiveType, sent_missive_q
from ..models.missive import MissiveAlreadySending
from ..utils import (
    get_progress_hooks,
    is_import_allowed,
    progress_step_default,
    send_chunk_size,
    stale_processing_cutoff,
    validate_import_paths,
)
from ..models.mixins import CommentTimestampedModel

logger = logging.getLogger(__name__)

MISSIVE_TYPE_ALL = "*"


def _resolve_task_method(obj, method_name: str):
    """Resolve a callable method on ``obj`` enforcing safety rules."""
    if not method_name or method_name.startswith("_"):
        raise ValidationError(
            _("Invalid task method '%(name)s': private/dunder methods are not allowed.") % {"name": method_name}
        )
    method = getattr(obj, method_name, None)
    if not callable(method):
        raise ValidationError(
            _("Task method '%(name)s' on %(obj)s is not callable.") % {"name": method_name, "obj": type(obj).__name__}
        )
    return method


#: ``external_task_backend`` of a run that sends from the campaign targets.
SELECTION_TASK = "django_pymissive.services.send.run_selection"

SENDING_RUN_DELETE_MESSAGE = _("A campaign send in progress cannot be deleted: cancel it first.")


def format_average_send_speed(seconds) -> str:
    """Human duration for one send. Empty when the speed is not known yet."""
    if seconds is None:
        return ""
    # Round to each unit's precision before picking it, so 59.996 s never
    # shows as "60.00 s" and 119.7 s never as "1 min 60 s".
    milliseconds = round(seconds * 1000)
    if milliseconds < 1000:
        return f"{milliseconds} ms"
    if round(seconds, 2) < 60:
        return f"{seconds:.2f} s"
    minutes, rest = divmod(round(seconds), 60)
    return f"{minutes} min {rest} s"


class MissiveScheduledCampaign(CommentTimestampedModel):
    """Scheduled send for a campaign.

    ``campaign_snapshot`` freezes the campaign configuration when the run
    starts, so later edits of the campaign do not rewrite this run's history.

    Run counters (``total_count`` / ``sent_count`` / ``error_count``) are
    derived live from the related missives via
    :meth:`MissiveScheduledCampaignQuerySet.with_counts`, so they cannot drift
    from the actual missive statuses. Being live, they follow the missives: the
    total of an ended run drops when a newer run reclaims a draft this one never
    sent. What the run *did* send stays put — see ``counts_by_status`` and
    ``history_count``, which keep the attempts a retry has archived.

    ``average_send_speed`` is stored, not derived: seconds per missive sent,
    rewritten at each progress step from the sent count just refreshed.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        verbose_name=_("ID"),
    )
    campaign = models.ForeignKey(
        "django_pymissive.MissiveCampaign",
        on_delete=models.CASCADE,
        related_name="to_missivecampaignsend",
        verbose_name=_("Campaign"),
        editable=False,
    )
    scheduled_send_date = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Scheduled send date"),
        help_text=_("Scheduled send date for the campaign (leave blank for immediate sending)"),
    )
    send_date = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
        verbose_name=_("Send date"),
        help_text=_("Actual send date for the campaign"),
    )
    ended_at = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
        verbose_name=_("Ended at"),
        help_text=_("Actual ended date for the campaign"),
    )
    average_send_speed = models.FloatField(
        null=True,
        blank=True,
        editable=False,
        verbose_name=_("Average speed per send"),
        help_text=_(
            "Average seconds per missive sent, measured from the start of this run. "
            "Refreshed at each progress step, together with the sent count."
        ),
    )
    missive_type = models.CharField(
        max_length=50,
        default=MISSIVE_TYPE_ALL,
        choices=[(MISSIVE_TYPE_ALL, _("All types"))] + MissiveType.choices,
        verbose_name=_("Missive type"),
        help_text=_("Restrict sending to missives of this type. '*' sends every type (default)."),
    )
    retry_failed = models.BooleanField(
        default=False,
        verbose_name=_("Retry failed"),
        help_text=_(
            "If enabled, the campaign's failed missives are archived and duplicated "
            "as fresh drafts when this run starts, then sent by it "
            "(already archived attempts and conversation messages excluded)."
        ),
    )
    progress_hook = models.CharField(
        max_length=500,
        blank=True,
        default="",
        verbose_name=_("Progress hook"),
        help_text=_(
            "Dotted path of a callable invoked with this run at each progress step. "
            "Leave blank to use settings.PYMISSIVE_PROGRESS_HOOK."
        ),
    )
    progress_step = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name=_("Progress step"),
        help_text=_(
            "How many times a full run notifies its progress hook. "
            "Leave blank to use settings.PYMISSIVE_PROGRESS_STEP (default 20)."
        ),
    )
    cancelled_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Cancelled at"),
        help_text=_("When set, the send loop stops before the next missive. Missives not yet sent stay in draft."),
    )
    cancel_reason = models.TextField(
        blank=True,
        default="",
        verbose_name=_("Cancel reason"),
        help_text=_("Optional note stored with the cancellation."),
    )

    # Optional external task object — replaces the built-in campaign backend.
    task_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_("Task object type"),
        help_text=_("Type of the external object that handles task dispatch/execution."),
    )
    task_object_id = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name=_("Task object ID"),
        help_text=_("ID of the external task object."),
    )
    task_object = GenericForeignKey("task_content_type", "task_object_id")
    task_object_arguments = JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Task object arguments"),
        help_text=_(
            "Arguments for the external task object. "
            "Supported keys: "
            '"run_method" (method called on the task object, default "run_campaign"), '
            '"kwargs" (dict of extra keyword arguments forwarded to the method). '
            "The method must be synchronous."
        ),
    )
    external_task_backend = models.CharField(
        max_length=500,
        blank=True,
        default="",
        verbose_name=_("External task backend"),
        help_text=_(
            "Dotted path to a callable invoked with ``(scheduled_id)`` to run "
            'the campaign (e.g. "myapp.tasks.send_campaign"). '
            "Must match settings.PYMISSIVE_ALLOWED_TASK_BACKENDS when set."
        ),
    )
    additional_config = JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Additional configuration"),
        help_text=_("Additional configuration as JSON"),
    )
    build_target_processors = JSONField(
        default=list,
        blank=True,
        verbose_name=_("Build target processors"),
        help_text=_(
            "Chain that builds missives for this run. Leave empty to copy "
            "the campaign's chain when this run is saved. A target with its "
            "own chain still replaces it."
        ),
    )
    campaign_snapshot = JSONField(
        default=dict,
        blank=True,
        editable=False,
        verbose_name=_("Campaign snapshot"),
        help_text=_(
            "Copy of the campaign configuration captured when this run starts. "
            "Later edits to the campaign do not change it."
        ),
    )

    objects = MissiveScheduledCampaignManager()

    class Meta:
        verbose_name = _("Campaign send")
        verbose_name_plural = _("Campaign sends")
        ordering = ["-scheduled_send_date", "-ended_at", "-created_at"]

    # ------------------------------------------------------------------
    # URL / view
    # ------------------------------------------------------------------

    def get_progress_path(self) -> str:
        """Relative URL for the live progress page. Returns ``""`` when unsaved."""
        if not self.pk:
            return ""
        return reverse("django_pymissive:scheduler_progress", args=[self.pk])

    def get_absolute_url(self):
        """Used by Django admin "View on site"."""
        return self.get_progress_path()

    def save(self, *args, **kwargs):
        self.validate_cancellation()
        if self._state.adding:
            self._copy_build_target_processors_from_campaign()
        super().save(*args, **kwargs)

    def _copy_build_target_processors_from_campaign(self) -> None:
        """Fill an empty chain from the campaign, once, when the run is created.

        Later saves leave the chain alone, so it can be emptied on purpose.
        """
        if self.build_target_processors or not self.campaign_id:
            return
        if "campaign" in self._state.fields_cache:
            source = self.campaign.build_target_processors
        else:
            from .campaign import MissiveCampaign

            source = (
                MissiveCampaign.objects.filter(pk=self.campaign_id)
                .values_list("build_target_processors", flat=True)
                .first()
            )
        if source:
            self.build_target_processors = list(source)

    # ------------------------------------------------------------------
    # Live counters (annotated — no stored fields)
    # ------------------------------------------------------------------

    @classmethod
    def _count_fields(cls):
        """Every annotation name ``with_counts`` produces — read from its source.

        Derived rather than listed again: a counter added to
        :func:`count_annotations` is immediately readable on a non-annotated
        instance too, instead of silently answering 0 here.
        """
        return list(count_annotations())

    def _fetch_counts(self):
        """Compute the run counters live from the related missives."""
        annotated = type(self).objects.with_counts().filter(pk=self.pk).first()
        fields = self._count_fields()
        if annotated is None:
            return {key: 0 for key in fields}
        return {key: getattr(annotated, key, 0) or 0 for key in fields}

    def _cached_counts(self):
        """Live counters for a non-annotated instance, queried once and cached."""
        cache = self.__dict__.get("_counts_cache")
        if cache is None:
            cache = self._fetch_counts()
            self.__dict__["_counts_cache"] = cache
        return cache

    def refresh_counts(self):
        """Load fresh counters onto the instance (used between progress steps)."""
        for key, value in self._fetch_counts().items():
            self.__dict__[key] = value
        self.__dict__.pop("_counts_cache", None)
        self.__dict__.pop("_pending_targets_cache", None)
        return self

    def selection_channels(self) -> list[str]:
        """Channels a selection run builds, narrowed by ``missive_type``."""
        channels = list((self.additional_config or {}).get("missive_types") or [])
        if self.missive_type and self.missive_type != MISSIVE_TYPE_ALL:
            channels = [channel for channel in channels if channel == self.missive_type]
        return channels

    def pending_targets_by_type(self) -> dict:
        """Targets of an open selection run with no missive yet, per channel.

        They count in the total before their missive is built, so the
        progress has its final denominator from the start of the run.
        """
        if self.external_task_backend != SELECTION_TASK or self.ended_at:
            return {}
        cache = self.__dict__.get("_pending_targets_cache")
        if cache is None:
            from django.db.models import Count

            from .campaign_target import CampaignTarget

            rows = (
                CampaignTarget.objects.filter(
                    CampaignTarget.active_q(),
                    campaign_id=self.campaign_id,
                    missive_type__in=self.selection_channels(),
                )
                .values("missive_type")
                .order_by()
                .annotate(n=Count("id"))
            )
            cache = {row["missive_type"]: row["n"] for row in rows}
            self.__dict__["_pending_targets_cache"] = cache
        return cache

    @classmethod
    def prefetch_pending_targets(cls, runs) -> None:
        """Fill :meth:`pending_targets_by_type` for many runs in one query."""
        from django.db.models import Count

        from .campaign_target import CampaignTarget

        open_runs = [run for run in runs if run.external_task_backend == SELECTION_TASK and not run.ended_at]
        if not open_runs:
            return
        rows = (
            CampaignTarget.objects.filter(
                CampaignTarget.active_q(),
                campaign_id__in={run.campaign_id for run in open_runs},
            )
            .values("campaign_id", "missive_type")
            .order_by()
            .annotate(n=Count("id"))
        )
        by_campaign: dict = {}
        for row in rows:
            by_campaign.setdefault(row["campaign_id"], {})[row["missive_type"]] = row["n"]
        for run in open_runs:
            pending = by_campaign.get(run.campaign_id, {})
            run.__dict__["_pending_targets_cache"] = {
                channel: pending[channel] for channel in run.selection_channels() if channel in pending
            }

    def _count(self, name):
        """Annotated counter if present on the instance, else a live lookup."""
        if name in self.__dict__:
            return self.__dict__[name] or 0
        return self._cached_counts().get(name, 0) or 0

    def counts_by_type(self, *, only_active=False):
        """Per-channel breakdown: ``{missive_type: {"total", "sent", "error", "progress"}}``.

        With ``only_active=True`` channels with ``total == 0`` are omitted.
        """
        result: dict[str, dict[str, int]] = {}
        pending_targets = self.pending_targets_by_type()
        for missive_type in MISSIVE_TYPES:
            total = self._count(total_annotation_name(missive_type))
            total += pending_targets.get(missive_type, 0)
            if only_active and not total:
                continue
            sent = self._count(sent_annotation_name(missive_type))
            error = self._count(error_annotation_name(missive_type))
            result[missive_type] = {
                "total": total,
                "sent": sent,
                "error": error,
                "progress": round(sent / total * 100) if total else 0,
            }
        return result

    def _status_counts_by_type(self):
        """``{missive_type: {status: count}}`` from a single grouped query.

        Scoped like ``count_missive_<status>`` (every attempt of the run,
        archived ones included), so this breakdown may sum above the per-type
        total once a later run has retried some of these missives.
        """
        from django.db.models import Count

        from ..models.missive import Missive

        # _base_manager rather than self.to_missive: the default manager annotates
        # counts over reverse FKs whose LEFT JOINs survive .values(), which would
        # make Count group multiplied rows.
        rows = (
            Missive._base_manager.filter(scheduler=self, thread_type__in=ATTEMPT_THREADS)
            .values("missive_type", "status")
            .annotate(n=Count("id"))
        )
        result: dict[str, dict[str, int]] = {}
        for row in rows:
            result.setdefault(row["missive_type"], {})[row["status"]] = row["n"]
        return result

    def counts_by_status(self, *, only_active=False):
        """Overall status breakdown: ``{status: count}``.

        Covers every attempt of the run, including the ones a later retry
        archived, so the failures of a finished run stay readable. May therefore
        sum above :attr:`total_count`.

        With ``only_active=True`` statuses with ``count == 0`` are omitted.
        """
        result = {}
        for status in MissiveStatus:
            count = self._count(status_annotation_name(status))
            if only_active and not count:
                continue
            result[status] = count
        return result

    @property
    def total_count(self):
        """Missives attached to this run (any status, archived attempts excluded).

        An open selection run also counts its targets still without a missive.
        """
        return self._count("count_total") + sum(self.pending_targets_by_type().values())

    @property
    def history_count(self):
        """Attempts of this run a later retry archived — no longer in the total."""
        return self._count(thread_annotation_name(MissiveThreadType.HISTORY))

    @property
    def total_sent_count(self):
        """Missives no longer in DRAFT, summed across every channel."""
        return self._count("count_sent")

    @property
    def total_pending_count(self):
        """Missives of this run still waiting to be sent, unbuilt targets included."""
        return self._count("count_pending") + sum(self.pending_targets_by_type().values())

    @property
    def total_error_count(self):
        """Missives in an error status, summed across every channel."""
        return self._count("count_error")

    # Short aliases, kept for backwards compatibility — one per overall counter,
    # so a caller can iterate over the statuses it displays.
    @property
    def sent_count(self):
        return self.total_sent_count

    @property
    def pending_count(self):
        return self.total_pending_count

    @property
    def error_count(self):
        return self.total_error_count

    @property
    def progress(self):
        """Completion percentage (0-100) of the current/last run.

        An ended run with nothing left is done, not at 0%: either it had nothing
        to send, or a newer run took over the drafts it never sent.
        """
        total = self.total_count
        if not total:
            return 100 if self.ended_at else 0
        return round(self.total_sent_count / total * 100)

    def progress_payload(self):
        """JSON-serializable progress snapshot for the scheduler front page."""
        by_type = {}
        status_by_type = self._status_counts_by_type()
        for missive_type, counts in self.counts_by_type(only_active=True).items():
            by_type[missive_type] = {
                "label": MISSIVE_TYPES.get(missive_type, missive_type),
                **counts,
                "by_status": status_by_type.get(missive_type, {}),
            }
        by_status = {}
        for status, count in self.counts_by_status(only_active=True).items():
            by_status[status] = {
                "label": str(MissiveStatus(status).label),
                "count": count,
            }
        return {
            "id": str(self.pk),
            "campaign_id": str(self.campaign_id),
            "campaign_subject": self.campaign.subject,
            "missive_type": self.missive_type,
            "status": self.run_status,
            "running": self.is_running,
            "scheduled_send_date": (self.scheduled_send_date.isoformat() if self.scheduled_send_date else None),
            "send_date": self.send_date.isoformat() if self.send_date else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "cancelled_at": self.cancelled_at.isoformat() if self.cancelled_at else None,
            "cancel_reason": self.cancel_reason or "",
            "total_count": self.total_count,
            "total_sent_count": self.total_sent_count,
            "total_pending_count": self.total_pending_count,
            "total_error_count": self.total_error_count,
            "history_count": self.history_count,
            "progress": self.progress,
            "average_send_speed": self.average_send_speed,
            "average_send_speed_display": format_average_send_speed(self.average_send_speed),
            "by_type": by_type,
            "by_status": by_status,
        }

    # ------------------------------------------------------------------
    # Status helpers
    # ------------------------------------------------------------------

    @property
    def is_running(self):
        """True while the send task has started but not finished."""
        return self.send_date is not None and self.ended_at is None

    @property
    def is_stale(self) -> bool:
        """True when this open run missed its heartbeat timeout.

        A SIGKILL skips the ``finally`` that sets ``ended_at``. After
        ``PYMISSIVE_STALE_PROCESSING_SECONDS`` without a heartbeat the run
        is treated as dead so ``start_campaign`` can start again.

        A run still waiting for ``scheduled_send_date`` is not stale.
        """
        if self.ended_at:
            return False
        if self.scheduled_send_date and self.scheduled_send_date > timezone.now():
            return False
        cutoff = stale_processing_cutoff()
        if cutoff is None:
            return False
        stamps = [stamp for stamp in (self.updated_at, self.send_date) if stamp is not None]
        stamp = max(stamps) if stamps else self.created_at
        return stamp is not None and stamp <= cutoff

    @property
    def is_sending(self) -> bool:
        """True while a live worker is sending this run: it cannot be deleted.

        A stale run is not sending: its worker is dead and no loop would read
        a cancellation, so it must stay deletable.
        """
        return self.is_running and not self.is_stale

    def delete(self, using=None, keep_parents=False):
        if self.is_sending:
            raise ProtectedError(str(SENDING_RUN_DELETE_MESSAGE), {self})
        return super().delete(using=using, keep_parents=keep_parents)

    def heartbeat(self) -> None:
        """Touch ``updated_at`` so a live worker is not mistaken for a crash."""
        now = timezone.now()
        type(self).objects.filter(pk=self.pk, ended_at__isnull=True).update(updated_at=now)
        self.updated_at = now

    @property
    def run_status(self):
        """``pending`` | ``running`` | ``cancelled`` | ``completed``."""
        if self.cancelled_at:
            return "cancelled"
        if self.ended_at:
            return "completed"
        if self.send_date:
            return "running"
        return "pending"

    @property
    def can_send(self) -> bool:
        """True when this run has not started, not ended, not cancelled, and is due."""
        if self.send_date or self.ended_at or self.cancelled_at:
            return False
        if self.scheduled_send_date and self.scheduled_send_date > timezone.now():
            return False
        return True

    # ------------------------------------------------------------------
    # Task dispatch
    # ------------------------------------------------------------------

    def start_scheduled_campaign(self):
        """Async-dispatch the campaign run via the configured backend, once committed.

        A worker started inside the caller's transaction could read the run
        before it exists, or before its drafts are attached to it.
        """
        from ..task import get_campaign_backend

        backend = get_campaign_backend()
        run_id = str(self.id)
        transaction.on_commit(lambda: backend.delay(run_id))

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def run_with_tracking(self) -> None:
        """Claim the run atomically, execute it, and always finalize tracking.

        The ``send_date`` claim is a single conditional ``UPDATE … WHERE
        send_date IS NULL``: atomic on every backend and safe against concurrent
        workers. The same UPDATE freezes ``campaign_snapshot`` so later edits
        of the campaign do not rewrite this run's history. On completion
        (success or failure) ``ended_at`` is set; on failure the error is recorded in
        ``additional_config['last_error']`` and re-raised.
        """
        now = timezone.now()
        with transaction.atomic():
            from .campaign import MissiveCampaign

            snapshot = MissiveCampaign.objects_plain.get(pk=self.campaign_id).to_snapshot()
            claimed = (
                type(self)
                .objects.filter(pk=self.pk, send_date__isnull=True)
                .update(
                    send_date=now,
                    campaign_snapshot=snapshot,
                    updated_at=now,
                )
            )
            if not claimed:
                self.refresh_from_db()
                if self.is_stale:
                    self._finalize_run(str(_("Stale run: timed out waiting for a heartbeat.")))
                    from .missive import Missive

                    Missive.reclaim_stale_processing(scheduler=self)
                return
            self.send_date = now
            self.updated_at = now
            self.campaign_snapshot = snapshot

            # When retry_failed is set, re-queue the campaign's failures at claim
            # time as fresh DRAFTs. Done here (not in run_campaign) so retry
            # works generically for every backend the task dispatches to.
            if self.retry_failed:
                self._retry_error_missives()

            # Attach all relevant DRAFT missives to this scheduler in the same
            # transaction as the send_date claim, so live count annotations are
            # accurate from the very first progress poll. Same claim rule as
            # ``start_campaign`` — drafts left behind by an ended run included.
            #
            # Claimed unconditionally: guarding on an empty ``to_missive`` made
            # ``retry_failed`` substitutive instead of additive, since
            # ``_retry_error_missives`` has just filled it with the retry drafts.
            # The campaign's own pending missives were then left with no run to
            # send them. Re-claiming costs nothing and takes nothing from
            # anybody: the drafts of a run still open — this one's included —
            # are not claimable.
            qs = self.campaign.claimable_send_queryset()
            if self.missive_type and self.missive_type != MISSIVE_TYPE_ALL:
                qs = qs.filter(missive_type=self.missive_type)
            qs.update(scheduler=self)

        error = None
        try:
            self.run_campaign()
        except Exception as exc:
            error = str(exc)
            raise
        finally:
            self._finalize_run(error)

    def _finalize_run(self, error: str | None) -> None:
        """Set ``ended_at`` and persist an optional error."""
        self.ended_at = timezone.now()
        update_fields = ["ended_at"]
        if error is not None:
            config = dict(self.additional_config or {})
            config["last_error"] = error
            self.additional_config = config
            update_fields.append("additional_config")
        self.save(update_fields=update_fields)

    def get_missives(self):
        """Return the queryset of DRAFT missives to process for this run.

        When missives were bulk-attached to the run via the ``scheduler`` FK
        (see :meth:`MissiveCampaign.start_campaign`), we query through that
        relation for accuracy. Otherwise fall back to the campaign relation
        (useful for runs created manually without the bulk-update step).
        Filtered by ``missive_type`` when not ``"*"``.

        The fallback claims what
        :meth:`MissiveCampaign.claimable_send_queryset` allows — not every draft
        of the campaign: a run must not process the missives another open run is
        working on, and a conversation message is not a send at all.
        """
        from .missive import Missive

        if self.to_missive.exists():
            Missive.reclaim_stale_processing(scheduler=self)
            qs = self.to_missive.filter(
                status=MissiveStatus.DRAFT,
                thread_type=MissiveThreadType.MISSIVE,
            )
        else:
            Missive.reclaim_stale_processing(campaign=self.campaign)
            qs = self.campaign.claimable_send_queryset()
        if self.missive_type and self.missive_type != MISSIVE_TYPE_ALL:
            qs = qs.filter(missive_type=self.missive_type)
        return qs

    @staticmethod
    def claim_missive(missive) -> bool:
        """Atomically flip ``missive`` from DRAFT/ERROR to PROCESSING.

        Returns True only if this call won the claim. Prefer
        :meth:`Missive.send_missive`, which claims itself — a pre-claim here
        would make that second ``UPDATE`` lose.
        """
        return missive.claim_for_send()

    def iter_claimed_missives(self):
        """Yield each missive this run successfully claimed (DRAFT/ERROR→PROCESSING)."""
        for missive in list(self.get_missives()):
            if self.claim_missive(missive):
                yield missive

    @staticmethod
    def _mark_missive_error(missive, exc: Exception) -> None:
        """Append an ERROR event for an unexpected send failure."""
        missive._record_send_failure(exc)

    def resolve_progress_step(self) -> int:
        """Notifications aimed at over this run.

        ``progress_step`` when set, otherwise ``settings.PYMISSIVE_PROGRESS_STEP``.
        """
        if self.progress_step:
            return self.progress_step
        return progress_step_default()

    def _progress_stride(self, total: int) -> int:
        """Missives between two progress-hook calls.

        :meth:`resolve_progress_step` is how many times a full run should notify.
        A shorter run notifies after every missive.
        """
        steps = max(1, self.resolve_progress_step())
        if total <= 0:
            return 1
        return max(1, (total + steps - 1) // steps)

    def process_missives(self, send_fn=None) -> list:
        """Send each DRAFT missive best-effort.

        ``send_fn(missive)`` defaults to ``missive.send_missive()``, which
        claims the row. A lost claim is skipped (another worker owns the
        send). Other failures are recorded on the missive (``ERROR`` status +
        event); the batch continues. Returns a list of
        ``(missive_pk, error_message)`` for failed missives.

        Each progress step stores :attr:`average_send_speed` from the sent count
        just refreshed, including after the last missive. The speed covers this
        loop only: the time a selection run spent building its drafts, and
        missives sent before the loop started, are left out. When a progress hook
        is configured (this run's ``progress_hook``, or
        ``settings.PYMISSIVE_PROGRESS_HOOK`` when that field is blank), each
        hook receives this run about :meth:`resolve_progress_step` times.
        The start, each step and a cancellation are also logged at ``INFO``.

        Before each missive the loop re-reads ``cancelled_at``. A cancellation
        stops the run and leaves the remaining drafts unsent.

        Only the primary keys are read up front; the missives themselves are
        loaded ``settings.PYMISSIVE_SEND_CHUNK_SIZE`` at a time. A missive
        deleted meanwhile is skipped.
        """
        if send_fn is None:

            def send_fn(missive):
                missive.send_missive()

        pks = list(self.get_missives().values_list("pk", flat=True))
        hooks = self.resolve_progress_hooks()
        total = len(pks)
        stride = self._progress_stride(total)
        failures: list[tuple[object, str]] = []
        logger.info("Scheduled campaign %s: sending %s missive(s)", self.pk, total)
        self._refresh_sent_count()
        speed_origin = (timezone.now(), self.total_sent_count)
        for index, missive in enumerate(self._iter_in_chunks(pks), start=1):
            if self.checkpoint():
                if self.cancelled_at:
                    self._record_step_progress(hooks, speed_origin)
                    logger.info(
                        "Scheduled campaign %s cancelled before missive %s/%s: %s",
                        self.pk,
                        index,
                        total,
                        self.cancel_reason or "no reason given",
                    )
                break
            if missive is not None:
                self._send_one(missive, send_fn, failures)
            if index % stride == 0 or index == total:
                self._record_step_progress(hooks, speed_origin)
                logger.info(
                    "Scheduled campaign %s: %s/%s processed, %s failed, %s s per send",
                    self.pk,
                    index,
                    total,
                    len(failures),
                    f"{self.average_send_speed:.2f}" if self.average_send_speed else "-",
                )
        return failures

    @staticmethod
    def _iter_in_chunks(pks):
        """Yield the missive of each pk in order, or ``None`` when it was deleted."""
        from .missive import Missive

        size = send_chunk_size()
        for start in range(0, len(pks), size):
            chunk = pks[start : start + size]
            loaded = Missive.objects.in_bulk(chunk)
            for pk in chunk:
                yield loaded.pop(pk, None)

    def _send_one(self, missive, send_fn, failures) -> None:
        """Send *missive*; record it in *failures* when the send fails."""
        try:
            send_fn(missive)
        except MissiveAlreadySending:
            return
        except Exception as exc:
            self._mark_missive_error(missive, exc)
            failures.append((missive.pk, str(exc)))
            logger.exception(
                "send_missive failed for missive %s in scheduler %s",
                missive.pk,
                self.pk,
            )
            return
        missive.refresh_from_db(fields=["status"])
        if missive.status == MissiveStatus.ERROR:
            failures.append((missive.pk, missive.last_send_error() or str(_("Send failed."))))

    def _retry_error_missives(self) -> int:
        """Re-queue failed missives for another send attempt.

        Every failure — send-time (``ERROR``) as well as delivery
        (``FAILED``, ``PARTIALLY_FAILED``) — is archived as ``HISTORY`` and
        duplicated as a fresh DRAFT attached to this run, so the provider sees a
        new submission. The archived row keeps its ``scheduler``: rewriting that
        FK would hand the failure over to this run, which never sent it, and
        erase it from the report of the run that did.

        Live sends only: archived attempts are already retried through their
        replacement, and a failed conversation message is not a campaign send.
        """
        base_qs = self.campaign.to_missive.filter(
            thread_type=MissiveThreadType.MISSIVE,
            status__in=ERROR_STATUSES,
        )
        if self.missive_type and self.missive_type != MISSIVE_TYPE_ALL:
            base_qs = base_qs.filter(missive_type=self.missive_type)

        retried = 0
        with transaction.atomic():
            for missive in base_qs:
                missive.thread_type = MissiveThreadType.HISTORY
                missive.save(update_fields=["thread_type"])
                new_missive = missive.duplicate_missive(
                    thread_type=MissiveThreadType.MISSIVE,
                    thread_id=missive.thread_id,
                    resend=True,
                )
                new_missive.scheduler = self
                new_missive.save(update_fields=["scheduler"])
                retried += 1

        return retried

    def run_campaign(self):
        """Execute the campaign — task_object, external backend, or built-in loop."""
        if self.task_content_type_id and self.task_object_id:
            obj = self.task_object
            if obj is None:
                raise ValidationError(_("Task object no longer exists."))
            method_name = (self.task_object_arguments or {}).get("run_method", "run_campaign")
            extra_kwargs = (self.task_object_arguments or {}).get("kwargs", {})
            method = _resolve_task_method(obj, method_name)
            method(self.id, **extra_kwargs)
        elif self.external_task_backend:
            if not is_import_allowed(self.external_task_backend):
                raise ValidationError(_("Backend '%(path)s' is not allowed.") % {"path": self.external_task_backend})
            import_string(self.external_task_backend)(self.id)
        else:
            self.process_missives()

    def validate_cancellation(self) -> None:
        """Only a started run carries a cancellation date."""
        if self.cancelled_at and not self.send_date:
            raise ValidationError(
                {
                    "cancelled_at": _("A run that has not started cannot be cancelled."),
                }
            )

    def _validate_progress_hook(self):
        progress_hook = (self.progress_hook or "").strip()
        if not progress_hook:
            return
        try:
            hooks = get_progress_hooks(progress_hook)
        except ImportError:
            raise ValidationError(
                {
                    "progress_hook": _("Progress hook %(path)s cannot be imported.") % {"path": progress_hook},
                }
            )
        if not all(callable(hook) for hook in hooks):
            raise ValidationError(
                {
                    "progress_hook": _("Progress hook %(path)s is not callable.") % {"path": progress_hook},
                }
            )

    def _validate_ended_cancellation(self):
        if not (self.cancelled_at and self.ended_at):
            return
        stored = type(self).objects.filter(pk=self.pk).values_list("cancelled_at", flat=True).first()
        if stored is None:
            raise ValidationError(
                {
                    "cancelled_at": _("A run that has ended cannot be cancelled."),
                }
            )

    def _validate_backend(self):
        if self.external_task_backend and not is_import_allowed(self.external_task_backend):
            raise ValidationError(
                {
                    "external_task_backend": _(
                        "Backend '%(path)s' is not allowed by settings.PYMISSIVE_ALLOWED_TASK_BACKENDS."
                    )
                    % {"path": self.external_task_backend}
                }
            )

    def _validate_task_object_arguments(self):
        args = self.task_object_arguments or {}
        run_method = args.get("run_method", "run_campaign")
        if run_method.startswith("_"):
            raise ValidationError(
                {
                    "task_object_arguments": _(
                        "run_method '%(name)s' is invalid: private/dunder methods are not allowed."
                    )
                    % {"name": run_method}
                }
            )
        extra_kwargs = args.get("kwargs", {})
        if not isinstance(extra_kwargs, dict):
            raise ValidationError(
                {
                    "task_object_arguments": _('"kwargs" must be a JSON object (dict), got %(type)s.')
                    % {"type": type(extra_kwargs).__name__}
                }
            )

    def clean(self):
        """Validate the configured runner and the cancellation."""
        super().clean()
        self.validate_cancellation()
        validate_import_paths(self, "progress_hook", "build_target_processors")
        self._validate_progress_hook()
        self._validate_ended_cancellation()
        self._validate_backend()
        self._validate_task_object_arguments()

    # ------------------------------------------------------------------
    # Progress hooks and cancellation
    # ------------------------------------------------------------------

    def resolve_progress_hooks(self):
        """Hooks for this run: ``progress_hook`` when set, otherwise the setting.

        A hook that cannot be imported is logged and dropped: like a hook
        that raises, it must not fail the send.
        """
        override = (self.progress_hook or "").strip()
        try:
            return get_progress_hooks(override or None)
        except ImportError:
            logger.exception(
                "Progress hook %r cannot be imported for scheduled campaign %s",
                override or "settings.PYMISSIVE_PROGRESS_HOOK",
                self.pk,
            )
            return []

    def pull_cancellation(self) -> bool:
        """Reload ``cancelled_at`` and ``cancel_reason`` from the database.

        True when the run was cancelled, was ended by another process (a
        stale-run finalization), or the row no longer exists. The in-memory
        copy is what a worker loaded at the start; an admin save during the
        send is only visible through this read.
        """
        row = type(self).objects.filter(pk=self.pk).values_list("cancelled_at", "cancel_reason", "ended_at").first()
        if row is None:
            return True
        self.cancelled_at = row[0]
        self.cancel_reason = row[1] or ""
        if row[2] is not None:
            logger.warning(
                "Scheduled campaign %s was ended by another process: stopping its send loop",
                self.pk,
            )
            return True
        return self.cancelled_at is not None

    def cancel(self, reason: str = "") -> bool:
        """Ask the worker to stop before its next missive.

        Only a run that started, has not ended and is not cancelled yet is
        touched, in one conditional ``UPDATE`` so the worker cannot race it.
        Returns whether this call cancelled the run.
        """
        now = timezone.now()
        updated = (
            type(self)
            .objects.filter(
                pk=self.pk,
                send_date__isnull=False,
                ended_at__isnull=True,
                cancelled_at__isnull=True,
            )
            .update(cancelled_at=now, cancel_reason=reason, updated_at=now)
        )
        if updated:
            self.cancelled_at = now
            self.cancel_reason = reason
        return bool(updated)

    def checkpoint(self) -> bool:
        """Heartbeat, then tell whether the worker must stop.

        One ``UPDATE`` per missive in the usual case: it only touches a run
        still open and not cancelled. When it matches no row, the cancellation
        is read back with :meth:`pull_cancellation`.
        """
        now = timezone.now()
        touched = (
            type(self)
            .objects.filter(
                pk=self.pk,
                ended_at__isnull=True,
                cancelled_at__isnull=True,
            )
            .update(updated_at=now)
        )
        if touched:
            self.updated_at = now
            return False
        return self.pull_cancellation()

    def _record_step_progress(self, hooks, speed_origin):
        """Refresh the sent count, store the average speed, then notify hooks.

        Called at each progress step, including the last missive and a
        cancellation. Without hooks, only the sent count is read: the full
        set of counters is what a hook may look at, not the speed.
        *speed_origin* is ``(started_at, sent_before)`` taken when the send
        loop started.
        """
        if hooks:
            self.refresh_counts()
        else:
            self._refresh_sent_count()
        self._update_average_send_speed(*speed_origin)
        if hooks:
            self._notify_progress(hooks)

    def _refresh_sent_count(self) -> None:
        """Reload ``count_sent`` alone and drop the other cached counters."""
        from .missive import Missive

        for key in self._count_fields():
            self.__dict__.pop(key, None)
        self.__dict__.pop("_counts_cache", None)
        self.__dict__.pop("_pending_targets_cache", None)
        self.__dict__["count_sent"] = Missive._base_manager.filter(
            sent_missive_q(),
            scheduler_id=self.pk,
            thread_type=MissiveThreadType.MISSIVE,
        ).count()

    def _update_average_send_speed(self, started_at, sent_before) -> None:
        """Seconds per missive sent since *started_at*, from the current counts."""
        sent = self.total_sent_count - sent_before
        if sent <= 0:
            return
        elapsed = (timezone.now() - started_at).total_seconds()
        if elapsed < 0:
            return
        speed = elapsed / sent
        self.average_send_speed = speed
        type(self).objects.filter(pk=self.pk).update(average_send_speed=speed)

    def _notify_progress(self, hooks):
        """Call each progress hook, isolating hook errors."""
        for hook in hooks:
            try:
                hook(self)
            except Exception:
                logger.exception(
                    "Progress hook %r failed for scheduled campaign %s",
                    getattr(hook, "__name__", hook),
                    self.pk,
                )
