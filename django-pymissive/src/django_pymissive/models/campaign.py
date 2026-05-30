"""Missive campaign models."""

import uuid

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.module_loading import import_string
from django.utils.translation import gettext_lazy as _

from ..managers.campaign import MissiveCampaignManager
from ..models.mixins import CommentTimestampedModel, ConfigMixin, ProcessorsMixin
from ..models.choices import MissiveStatus, MissivePriority, AcknowledgementLevel, MissiveDeliveryMode, MissiveType
from django_geoaddress.fields import GeoaddressField
from phonenumber_field.modelfields import PhoneNumberField
from ..fields import RichTextField, JSONField

MISSIVE_TYPE_ALL = "*"


def _allowed_task_backends():
    """Return the configured allowlist for ``external_task_backend`` paths.

    ``settings.PYMISSIVE_ALLOWED_TASK_BACKENDS`` may be:
    - **None / unset** → no restriction (permissive; lock down in production).
    - **list/tuple** → each entry is matched as an exact dotted path OR a
      module prefix (``"myapp.tasks"`` allows ``"myapp.tasks.anything"``).
    """
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
    """Resolve a callable method on ``obj`` enforcing safety rules.

    - Private/dunder names (leading underscore) are always rejected.
    - The resolved attribute must be callable.
    """
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
    body_html = RichTextField(
        blank=True,
        verbose_name=_("Body HTML"),
        help_text=_("Campaign email HTML body"),
    )
    body_text = models.TextField(
        blank=True,
        verbose_name=_("Body text"),
        help_text=_("Campaign body text"),
    )

    # SMS
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
    body_sms = models.TextField(
        blank=True,
        verbose_name=_("Body SMS"),
        help_text=_("Campaign body SMS"),
    )

    # Address / LRE
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
    acknowledgement_lre = models.CharField(
        max_length=50,
        choices=AcknowledgementLevel.choices,
        default=AcknowledgementLevel.BASIC_DELIVERY,
        verbose_name=_("Acknowledgement Level"),
        help_text=_("Desired acknowledgement level for delivery proof"),
    )
    delivery_mode_lre = models.CharField(
        max_length=50,
        choices=MissiveDeliveryMode.choices,
        default=MissiveDeliveryMode.NORMAL,
        verbose_name=_("Delivery Mode"),
        help_text=_("Delivery mode (economic, normal, premium, express)"),
    )
    priority_lre = models.CharField(
        max_length=20,
        choices=MissivePriority.choices,
        default=MissivePriority.NORMAL,
        verbose_name=_("Priority"),
        help_text=_("Priority level"),
    )
    first_document = RichTextField(
        blank=True,
        verbose_name=_("First Document"),
        help_text=_("First document content (HTML, converted to PDF for LRE)"),
    )

    objects = MissiveCampaignManager()
    # Plain manager for select_for_update (PostgreSQL rejects FOR UPDATE with GROUP BY)
    objects_plain = models.Manager()

    class Meta:
        verbose_name = _("Campaign")
        verbose_name_plural = _("Campaigns")
        ordering = ["-created_at", "subject"]

    def __str__(self):
        return self.subject

    def get_browser_preview_path(self, *, preview_kind: str = "email") -> str:
        """Relative URL for the staff preview of this campaign.

        ``preview_kind`` selects which template will be rendered server-side
        (email, sms, postal — see ``PreviewView``). Returns ``""`` for an
        unsaved campaign.
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

    def start_campaign(self):
        """Start the campaign."""
        with transaction.atomic():
            campaign = MissiveCampaign.objects_plain.select_for_update().get(pk=self.pk)
            if campaign.metadata.get("processing"):
                raise ValidationError(_("Campaign is already being processed."))
            campaign.metadata = {**dict(campaign.metadata), "processing": True}
            campaign.save(update_fields=["metadata"])
            scheduled = campaign.to_missivecampaignsend.create(
                campaign=campaign,
                scheduled_send_date=timezone.now()
            )
            scheduled.start_scheduled_campaign()


class MissiveScheduledCampaign(CommentTimestampedModel):
    """Scheduled send for a campaign."""

    campaign = models.ForeignKey(
        MissiveCampaign,
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

    # Optional external task object — replaces the built-in campaign backend.
    # The object's method is called instead of backend.delay() in
    # start_scheduled_campaign() and instead of send_missive() in run_campaign().
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
            "The method must be synchronous — it must complete all sending before "
            "returning, otherwise ended_at will be recorded before any missive is sent."
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
            "The callable must be synchronous — it must complete all sending "
            "before returning, otherwise ended_at will be recorded prematurely. "
            "Ignored when task_object is configured. "
            "Must match settings.PYMISSIVE_ALLOWED_TASK_BACKENDS when set."
        ),
    )

    additional_config = JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Additional configuration"),
        help_text=_("Additional configuration as JSON"),
    )

    class Meta:
        verbose_name = _("Campaign send")
        verbose_name_plural = _("Campaign sends")
        ordering = ["-scheduled_send_date", "-ended_at", "-id"]

    @property
    def can_send(self) -> bool:
        """True when this scheduled run has not started, not ended, and is due.

        * ``send_date`` not set → not yet started
        * ``ended_at`` not set → not yet finished
        * ``scheduled_send_date`` is None (immediate) OR in the past/now
        """
        if self.send_date or self.ended_at:
            return False
        if self.scheduled_send_date and self.scheduled_send_date > timezone.now():
            return False
        return True

    def run_with_tracking(self) -> None:
        """Claim the run atomically, execute it, and always finalize tracking.

        The ``send_date`` claim is a single conditional ``UPDATE … WHERE
        send_date IS NULL``: atomic on every backend (SQLite included) and
        returning the affected-row count, so two concurrent workers/requests
        can never start the same scheduled send twice — the loser returns
        early. On completion (success OR failure) ``ended_at`` is set and the
        campaign ``processing`` flag is cleared; on failure the error is
        recorded in ``additional_config['last_error']`` and re-raised.
        """
        now = timezone.now()
        claimed = (
            type(self)
            .objects.filter(pk=self.pk, send_date__isnull=True)
            .update(send_date=now)
        )
        if not claimed:
            # Already started by another worker/request — do nothing.
            return
        self.send_date = now

        error = None
        try:
            self.run_campaign()
        except Exception as exc:  # noqa: BLE001 — recorded then re-raised
            error = str(exc)
            raise
        finally:
            self._finalize_run(error)

    def _finalize_run(self, error: str | None) -> None:
        """Set ended_at (+ optional error) and clear the campaign processing flag.

        The ``processing`` flag is removed via a ``select_for_update`` read-
        modify-write so concurrent finalisations on the same campaign do not
        clobber each other's metadata keys.
        """
        self.ended_at = timezone.now()
        update_fields = ["ended_at"]
        if error is not None:
            config = dict(self.additional_config or {})
            config["last_error"] = error
            self.additional_config = config
            update_fields.append("additional_config")
        self.save(update_fields=update_fields)

        with transaction.atomic():
            campaign = (
                MissiveCampaign.objects_plain
                .select_for_update()
                .get(pk=self.campaign_id)
            )
            metadata = dict(campaign.metadata or {})
            metadata.pop("processing", None)
            campaign.metadata = metadata
            campaign.save(update_fields=["metadata"])

    def start_scheduled_campaign(self):
        """Async-dispatch the campaign run via the built-in backend.

        All paths go through the backend so the worker always calls
        ``run_with_tracking()`` → ``run_campaign()``.  The configured
        runner (task_object, external_task_backend, or built-in loop) is
        selected inside ``run_campaign()`` at execution time.
        """
        from ..task import get_campaign_backend
        backend = get_campaign_backend()
        backend.delay(self.id)

    def get_missives(self):
        """Return the queryset of missives to process for this scheduled run.

        Filters to DRAFT status and, when ``missive_type`` is not ``"*"``,
        restricts to that specific type.
        """
        qs = self.campaign.to_missive.filter(status=MissiveStatus.DRAFT)
        if self.missive_type and self.missive_type != MISSIVE_TYPE_ALL:
            qs = qs.filter(missive_type=self.missive_type)
        return qs

    @staticmethod
    def claim_missive(missive) -> bool:
        """Atomically flip ``missive`` from DRAFT to PROCESSING.

        Returns True only if *this* call won the claim. A single conditional
        ``UPDATE … WHERE status = DRAFT`` guarantees that two concurrent
        scheduled runs targeting the same missive can never both send it —
        the loser gets a 0 row-count and skips. Portable across all backends.
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
        """Yield each missive this run successfully claimed (DRAFT→PROCESSING).

        This is a *pure* claim iterator — no send and no error handling. The
        caller is responsible for sending and for handling failures. For the
        standard best-effort behaviour (continue on error, mark the failing
        missive), prefer :meth:`process_missives`.
        """
        for missive in list(self.get_missives()):
            if self.claim_missive(missive):
                yield missive

    @staticmethod
    def _mark_missive_error(missive, exc: Exception) -> None:
        """Move a missive to ERROR and record the failure (best-effort send)."""
        config = dict(missive.additional_config or {})
        config["last_error"] = str(exc)
        type(missive).objects.filter(pk=missive.pk).update(
            status=MissiveStatus.ERROR,
            additional_config=config,
        )
        missive.status = MissiveStatus.ERROR
        missive.additional_config = config

    def process_missives(self, send_fn=None) -> list:
        """Claim and send each DRAFT missive **best-effort**.

        ``send_fn(missive)`` defaults to ``missive.send_missive()``; pass a
        custom callable to inject per-missive logic (e.g. setting processors)
        before sending. A missive whose send raises is moved to ``ERROR`` with
        the error recorded in its ``additional_config['last_error']`` and the
        batch **continues** — one bad missive never blocks the rest.

        Returns a list of ``(missive_pk, error_message)`` for failed missives.

        .. important::
            When used from a ``task_object`` method or ``external_task_backend``,
            the runner **must be synchronous** — it must complete all sending
            before returning. Returning early after enqueuing async work will
            cause ``run_with_tracking()`` to record ``ended_at`` and clear the
            ``processing`` flag before any missive is actually sent.
        """
        if send_fn is None:
            def send_fn(missive):
                missive.send_missive()
        failures = []
        for missive in self.iter_claimed_missives():
            try:
                send_fn(missive)
            except Exception as exc:  # noqa: BLE001 — recorded per missive, batch continues
                self._mark_missive_error(missive, exc)
                failures.append((missive.pk, str(exc)))
        return failures

    def clean(self):
        """Validate the configured runner before it can ever be executed."""
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

    def run_campaign(self):
        """Execute the campaign — external task object or built-in loop.

        Runner resolution is validated (see :func:`_resolve_task_method` and
        :func:`_is_task_backend_allowed`) to avoid arbitrary code execution
        from DB-controlled fields.
        """
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
