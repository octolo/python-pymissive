"""Missive scheduled campaign model."""

import logging

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.module_loading import import_string
from django.utils.translation import gettext_lazy as _
from pymissive.config import MISSIVE_TYPES

from ..fields import JSONField
from ..managers.scheduler import (
    ERROR_STATUSES,
    MissiveScheduledCampaignManager,
    error_annotation_name,
    sent_annotation_name,
    total_annotation_name,
)
from ..models.choices import MissiveStatus, MissiveThreadType, MissiveType
from ..models.mixins import CommentTimestampedModel

logger = logging.getLogger(__name__)

MISSIVE_TYPE_ALL = "*"


def _allowed_task_backends():
    """Return the configured allowlist for ``external_task_backend`` paths."""
    return getattr(settings, "PYMISSIVE_ALLOWED_TASK_BACKENDS", None)


def _is_task_backend_allowed(path: str) -> bool:
    allowed = _allowed_task_backends()
    if allowed is None:
        return True
    for entry in allowed:
        if path == entry or path.startswith(f"{entry}."):
            return True
    return False


def _resolve_task_method(obj, method_name: str):
    """Resolve a callable method on ``obj`` enforcing safety rules."""
    if not method_name or method_name.startswith("_"):
        raise ValidationError(
            _("Invalid task method '%(name)s': private/dunder methods are not allowed.")
            % {"name": method_name}
        )
    method = getattr(obj, method_name, None)
    if not callable(method):
        raise ValidationError(
            _("Task method '%(name)s' on %(obj)s is not callable.")
            % {"name": method_name, "obj": type(obj).__name__}
        )
    return method


class MissiveScheduledCampaign(CommentTimestampedModel):
    """Scheduled send for a campaign.

    Run counters (``total_count`` / ``sent_count`` / ``error_count``) are
    derived live from the related missives via
    :meth:`MissiveScheduledCampaignQuerySet.with_counts`, so they cannot drift
    from the actual missive statuses.
    """

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
        help_text=_(
            "Scheduled send date for the campaign (leave blank for immediate sending)"
        ),
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
    missive_type = models.CharField(
        max_length=50,
        default=MISSIVE_TYPE_ALL,
        choices=[(MISSIVE_TYPE_ALL, _("All types"))] + MissiveType.choices,
        verbose_name=_("Missive type"),
        help_text=_(
            "Restrict sending to missives of this type. "
            "'*' sends every type (default)."
        ),
    )
    retry_failed = models.BooleanField(
        default=False,
        verbose_name=_("Retry failed"),
        help_text=_(
            "If enabled, missives that fail during this run are reset to DRAFT "
            "and retried once after the initial pass (history missives excluded)."
        ),
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
            "\"run_method\" (method called on the task object, default \"run_campaign\"), "
            "\"kwargs\" (dict of extra keyword arguments forwarded to the method). "
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
            "the campaign (e.g. \"myapp.tasks.send_campaign\"). "
            "Must match settings.PYMISSIVE_ALLOWED_TASK_BACKENDS when set."
        ),
    )
    additional_config = JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Additional configuration"),
        help_text=_("Additional configuration as JSON"),
    )

    objects = MissiveScheduledCampaignManager()

    # Target number of progress notifications for a full run, whatever the volume.
    PROGRESS_SAVE_STEPS = 20

    class Meta:
        verbose_name = _("Campaign send")
        verbose_name_plural = _("Campaign sends")
        ordering = ["-scheduled_send_date", "-ended_at", "-id"]

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

    # ------------------------------------------------------------------
    # Live counters (annotated — no stored fields)
    # ------------------------------------------------------------------

    @classmethod
    def _count_fields(cls):
        """All annotation names produced by ``with_counts`` (overall + per type)."""
        fields = ["count_total", "count_sent", "count_error"]
        for missive_type in MISSIVE_TYPES:
            fields.append(total_annotation_name(missive_type))
            fields.append(sent_annotation_name(missive_type))
            fields.append(error_annotation_name(missive_type))
        return fields

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
        return self

    def _count(self, name):
        """Annotated counter if present on the instance, else a live lookup."""
        if name in self.__dict__:
            return self.__dict__[name] or 0
        return self._cached_counts().get(name, 0) or 0

    def counts_by_type(self, *, only_active=False):
        """Per-channel breakdown: ``{missive_type: {"total", "sent", "error", "progress"}}``.

        With ``only_active=True`` channels with ``total == 0`` are omitted.
        """
        result = {}
        for missive_type in MISSIVE_TYPES:
            total = self._count(total_annotation_name(missive_type))
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

    @property
    def total_count(self):
        """Total missives attached to this run (any status)."""
        return self._count("count_total")

    @property
    def total_sent_count(self):
        """Missives no longer in DRAFT, summed across every channel."""
        return self._count("count_sent")

    @property
    def total_error_count(self):
        """Missives in an error status, summed across every channel."""
        return self._count("count_error")

    # Backwards-compatible aliases.
    @property
    def sent_count(self):
        return self.total_sent_count

    @property
    def error_count(self):
        return self.total_error_count

    @property
    def progress(self):
        """Completion percentage (0-100) of the current/last run."""
        total = self.total_count
        if not total:
            return 0
        return round(self.total_sent_count / total * 100)

    def progress_payload(self):
        """JSON-serializable progress snapshot for the scheduler front page."""
        by_type = {}
        for missive_type, counts in self.counts_by_type(only_active=True).items():
            by_type[missive_type] = {
                "label": MISSIVE_TYPES.get(missive_type, missive_type),
                **counts,
            }
        return {
            "id": str(self.pk),
            "campaign_id": str(self.campaign_id),
            "campaign_subject": self.campaign.subject,
            "missive_type": self.missive_type,
            "status": self.run_status,
            "running": self.is_running,
            "scheduled_send_date": (
                self.scheduled_send_date.isoformat() if self.scheduled_send_date else None
            ),
            "send_date": self.send_date.isoformat() if self.send_date else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "total_count": self.total_count,
            "total_sent_count": self.total_sent_count,
            "total_error_count": self.total_error_count,
            "progress": self.progress,
            "by_type": by_type,
        }

    # ------------------------------------------------------------------
    # Status helpers
    # ------------------------------------------------------------------

    @property
    def is_running(self):
        """True while the send task has started but not finished."""
        return self.send_date is not None and self.ended_at is None

    @property
    def run_status(self):
        """``pending`` | ``running`` | ``completed``."""
        if self.ended_at:
            return "completed"
        if self.send_date:
            return "running"
        return "pending"

    @property
    def can_send(self) -> bool:
        """True when this run has not started, not ended, and is due."""
        if self.send_date or self.ended_at:
            return False
        if self.scheduled_send_date and self.scheduled_send_date > timezone.now():
            return False
        return True

    # ------------------------------------------------------------------
    # Task dispatch
    # ------------------------------------------------------------------

    def start_scheduled_campaign(self):
        """Async-dispatch the campaign run via the configured backend."""
        from ..task import get_campaign_backend
        backend = get_campaign_backend()
        backend.delay(self.id)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def run_with_tracking(self) -> None:
        """Claim the run atomically, execute it, and always finalize tracking.

        The ``send_date`` claim is a single conditional ``UPDATE … WHERE
        send_date IS NULL``: atomic on every backend and safe against concurrent
        workers. On completion (success or failure) ``ended_at`` is set and the
        campaign ``processing`` flag is cleared; on failure the error is
        recorded in ``additional_config['last_error']`` and re-raised.
        """
        now = timezone.now()
        with transaction.atomic():
            claimed = (
                type(self)
                .objects.filter(pk=self.pk, send_date__isnull=True)
                .update(send_date=now)
            )
            if not claimed:
                return
            self.send_date = now

            # Attach all relevant DRAFT missives to this scheduler in the same
            # transaction as the send_date claim, so live count annotations are
            # accurate from the very first progress poll.
            if not self.to_missive.exists():
                qs = self.campaign.to_missive.filter(
                    status=MissiveStatus.DRAFT,
                    scheduler__isnull=True,
                )
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
        """Set ended_at (+ optional error) and clear the campaign processing flag."""
        self.ended_at = timezone.now()
        update_fields = ["ended_at"]
        if error is not None:
            config = dict(self.additional_config or {})
            config["last_error"] = error
            self.additional_config = config
            update_fields.append("additional_config")
        self.save(update_fields=update_fields)

        with transaction.atomic():
            from .campaign import MissiveCampaign
            campaign = (
                MissiveCampaign.objects_plain
                .select_for_update()
                .get(pk=self.campaign_id)
            )
            metadata = dict(campaign.metadata or {})
            metadata.pop("processing", None)
            campaign.metadata = metadata
            campaign.save(update_fields=["metadata"])

    def get_missives(self):
        """Return the queryset of DRAFT missives to process for this run.

        When missives were bulk-attached to the run via the ``scheduler`` FK
        (see :meth:`MissiveCampaign.start_campaign`), we query through that
        relation for accuracy. Otherwise fall back to the campaign relation
        (useful for runs created manually without the bulk-update step).
        Filtered by ``missive_type`` when not ``"*"``.
        """
        if self.to_missive.exists():
            qs = self.to_missive.filter(status=MissiveStatus.DRAFT)
        else:
            qs = self.campaign.to_missive.filter(status=MissiveStatus.DRAFT)
        if self.missive_type and self.missive_type != MISSIVE_TYPE_ALL:
            qs = qs.filter(missive_type=self.missive_type)
        return qs

    @staticmethod
    def claim_missive(missive) -> bool:
        """Atomically flip ``missive`` from DRAFT to PROCESSING.

        Returns True only if this call won the claim.
        """
        claimed = (
            type(missive)
            .objects.filter(pk=missive.pk, status=MissiveStatus.DRAFT)
            .update(status=MissiveStatus.PROCESSING)
        )
        if claimed:
            missive.status = MissiveStatus.PROCESSING
        return bool(claimed)

    def iter_claimed_missives(self):
        """Yield each missive this run successfully claimed (DRAFT→PROCESSING)."""
        for missive in list(self.get_missives()):
            if self.claim_missive(missive):
                yield missive

    @staticmethod
    def _mark_missive_error(missive, exc: Exception) -> None:
        """Move a missive to ERROR and record the failure."""
        config = dict(missive.additional_config or {})
        config["last_error"] = str(exc)
        type(missive).objects.filter(pk=missive.pk).update(
            status=MissiveStatus.ERROR,
            additional_config=config,
        )
        missive.status = MissiveStatus.ERROR
        missive.additional_config = config

    def process_missives(self, send_fn=None) -> list:
        """Claim and send each DRAFT missive best-effort.

        ``send_fn(missive)`` defaults to ``missive.send_missive()``. A missive
        whose send raises is moved to ``ERROR`` and the batch continues.
        Returns a list of ``(missive_pk, error_message)`` for failed missives.
        """
        if send_fn is None:
            def send_fn(missive):
                missive.send_missive()
        failures = []
        for missive in self.iter_claimed_missives():
            try:
                send_fn(missive)
            except Exception as exc:
                self._mark_missive_error(missive, exc)
                failures.append((missive.pk, str(exc)))
                logger.exception(
                    "send_missive failed for missive %s in scheduler %s",
                    missive.pk,
                    self.pk,
                )
        return failures

    def _retry_error_missives(self) -> int:
        """Reset failed campaign missives (excluding history) back to DRAFT for a second pass.

        Missives are re-attached to this scheduler so that live count annotations
        remain accurate. Returns the number of missives reset.
        """
        qs = self.campaign.to_missive.filter(
            status__in=ERROR_STATUSES,
        ).exclude(
            thread_type=MissiveThreadType.HISTORY,
        )
        if self.missive_type and self.missive_type != MISSIVE_TYPE_ALL:
            qs = qs.filter(missive_type=self.missive_type)
        return qs.update(status=MissiveStatus.DRAFT, scheduler=self)

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
            if not _is_task_backend_allowed(self.external_task_backend):
                raise ValidationError(
                    _("Backend '%(path)s' is not allowed.") % {"path": self.external_task_backend}
                )
            import_string(self.external_task_backend)(self.id)
        else:
            self.process_missives()
            if self.retry_failed and self._retry_error_missives():
                logger.info(
                    "Scheduler %s: retrying error missives (retry_on_error=True)",
                    self.pk,
                )
                self.process_missives()

    def clean(self):
        """Validate the configured runner."""
        super().clean()
        if self.external_task_backend and not _is_task_backend_allowed(self.external_task_backend):
            raise ValidationError({
                "external_task_backend": _(
                    "Backend '%(path)s' is not allowed by "
                    "settings.PYMISSIVE_ALLOWED_TASK_BACKENDS."
                ) % {"path": self.external_task_backend}
            })
        args = self.task_object_arguments or {}
        run_method = args.get("run_method", "run_campaign")
        if run_method.startswith("_"):
            raise ValidationError({
                "task_object_arguments": _(
                    "run_method '%(name)s' is invalid: private/dunder methods are not allowed."
                ) % {"name": run_method}
            })
        extra_kwargs = args.get("kwargs", {})
        if not isinstance(extra_kwargs, dict):
            raise ValidationError({
                "task_object_arguments": _(
                    "\"kwargs\" must be a JSON object (dict), got %(type)s."
                ) % {"type": type(extra_kwargs).__name__}
            })

    # ------------------------------------------------------------------
    # Progress hooks (used when PYMISSIVE_PROGRESS_ENABLED is True)
    # ------------------------------------------------------------------

    def _notify_progress(self, hooks):
        """Refresh counters then call each progress hook, isolating hook errors."""
        self.refresh_counts()
        for hook in hooks:
            try:
                hook(self)
            except Exception:
                logger.exception(
                    "Progress hook %r failed for scheduled campaign %s",
                    getattr(hook, "__name__", hook),
                    self.pk,
                )
