"""Ordered, typed steps of one campaign.

A step belongs to a single campaign and is not reused. Its presence is what
turns the channel on: there is no separate activation flag. Steps run in
``position`` order. That order is not a workflow: a failure does not block
the next step, and there is no delay or condition.

Channel content lives directly on this model. Proxy models expose one
missive type each without adding tables or columns.

Schema changes are not shipped as a migration. The project that deploys
django-pymissive creates the step table, the attachment M2M table and the two nullable foreign keys
(``Missive.campaign_step``, ``CampaignTarget.campaign_step``), narrows
``uniq_campaigntarget_pending`` to rows whose step is null, and adds
``uniq_campaigntarget_pending_step``.
"""

from __future__ import annotations

from typing import ClassVar

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.deletion import ProtectedError
from django.utils.translation import gettext_lazy as _
from django_geoaddress.fields import GeoaddressField
from phonenumber_field.modelfields import PhoneNumberField
from pymissive.config import normalize_missive_type

from ..fields import JSONField, RichTextField
from ..managers.campaign_step import CampaignStepManager
from ..utils import (
    apply_default_sender_fields,
    json_safe,
    sender_default_fields,
    serialize_model_for_context,
    snapshot_html_read_more,
)
from .choices import (
    MissiveThreadType,
    MissiveType,
    get_missive_support_from_type,
    sent_missive_q,
)
from .mixins import CommentTimestampedModel, ConfigMixin, ProcessorsMixin


class CampaignStep(ConfigMixin, ProcessorsMixin, CommentTimestampedModel):
    """One ordered send inside a campaign.

    Several steps may share a ``missive_type``. ``position`` is unique per
    campaign and is the only ordering key.
    """

    objects = CampaignStepManager()

    campaign = models.ForeignKey(
        "django_pymissive.MissiveCampaign",
        on_delete=models.CASCADE,
        related_name="to_campaignstep",
        verbose_name=_("Campaign"),
    )
    position = models.PositiveIntegerField(
        verbose_name=_("Position"),
        help_text=_("Launch order inside the campaign. Lower numbers run first."),
    )
    label = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("Label"),
        help_text=_("Name of this step in the campaign."),
    )
    missive_type = models.CharField(
        max_length=50,
        choices=MissiveType.choices,
        verbose_name=_("Missive type"),
        help_text=_("Channel this step sends on."),
    )
    subject = models.TextField(
        blank=True,
        default="",
        verbose_name=_("Subject"),
        help_text=_("Subject of this step. The campaign label is separate."),
    )
    duplex_printing = models.BooleanField(
        null=True,
        blank=True,
        default=None,
        verbose_name=_("Duplex printing"),
        help_text=_("Empty inherits the campaign value."),
    )
    color_printing = models.BooleanField(
        null=True,
        blank=True,
        default=None,
        verbose_name=_("Color printing"),
        help_text=_("Empty inherits the campaign value."),
    )
    sender_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name=_("Sender name"),
    )
    sender_email = models.EmailField(
        blank=True,
        null=True,
        verbose_name=_("Sender email"),
    )
    sender_phone = PhoneNumberField(
        blank=True,
        null=True,
        verbose_name=_("Sender phone"),
    )
    sender_address = GeoaddressField(
        blank=True,
        null=True,
        verbose_name=_("Sender address"),
    )
    reply_to_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name=_("Reply-To name"),
    )
    reply_to_email = models.EmailField(
        blank=True,
        null=True,
        verbose_name=_("Reply-To email"),
    )
    reply_to_address = GeoaddressField(
        max_length=512,
        blank=True,
        null=True,
        verbose_name=_("Reply-To address"),
    )
    brand_name = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name=_("Brand name"),
    )
    body_text = models.TextField(
        blank=True,
        default="",
        verbose_name=_("Plain text body"),
    )
    body_rich = RichTextField(
        blank=True,
        default="",
        verbose_name=_("Rich body"),
    )
    body_rich_snapshot_html = RichTextField(
        blank=True,
        default="",
        verbose_name=_("Rich body HTML snapshot"),
    )
    build_target_processors = JSONField(
        default=list,
        blank=True,
        verbose_name=_("Build target processors"),
        help_text=_(
            "Chain that builds a target's missive for this step. When non-empty, "
            "it replaces the campaign chain. A target or a run with its own chain "
            "still wins."
        ),
    )

    class Meta:
        verbose_name = _("Campaign step")
        verbose_name_plural = _("Campaign steps")
        ordering = ["campaign", "position", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["campaign", "position"],
                name="uniq_campaign_step_position",
            ),
        ]

    def __str__(self):
        name = self.label or self.get_missive_type_display()
        return f"{self.position}. {name}"

    def clean(self):
        super().clean()
        if self.missive_type and not normalize_missive_type(self.missive_type):
            raise ValidationError({"missive_type": _("Unknown missive type.")})
        self._validate_processor_paths("build_target_processors")

    def save(self, *args, **kwargs):
        canonical = normalize_missive_type(self.missive_type)
        if canonical:
            self.missive_type = canonical
        if kwargs.get("update_fields") is None:
            apply_default_sender_fields(self, sender_default_fields(self.support))
        super().save(*args, **kwargs)

    @property
    def can_remove(self) -> bool:
        """True while no live missive of this step has left the draft state."""
        annotated = getattr(self, "has_sent_missives", None)
        if annotated is None:
            annotated = self._sent_missives().exists()
            self.__dict__["has_sent_missives"] = annotated
        return not annotated

    def delete(self, using=None, keep_parents=False):
        if not self.can_remove:
            protected: set[models.Model] = set(self._sent_missives())
            if not protected:
                protected.add(self)
            raise ProtectedError(
                str(_("Cannot delete a campaign step that has missives which left the draft state.")),
                protected,
            )
        return super().delete(using=using, keep_parents=keep_parents)

    def _sent_missives(self):
        from .missive import Missive

        return Missive._base_manager.filter(
            sent_missive_q(),
            campaign_step=self,
            thread_type=MissiveThreadType.MISSIVE,
        )

    @property
    def support(self) -> str:
        return get_missive_support_from_type(self.missive_type) or ""

    @property
    def body_rich_snapshot_html_read_more(self):
        return snapshot_html_read_more(self.body_rich_snapshot_html)

    def to_snapshot(self) -> dict:
        """JSON-safe copy of this step, its configuration and file order."""
        config_data = serialize_model_for_context(self)
        for field in (
            "id",
            "campaign_id",
            "position",
            "label",
            "missive_type",
            "build_target_processors",
        ):
            config_data.pop(field, None)
        config_data = json_safe(config_data)
        attachments = [
            {"id": str(attachment.pk), "position": attachment.priority}
            for attachment in self.attachments.order_by("priority", "pk")
        ]
        return {
            "id": self.pk,
            "position": self.position,
            "label": self.label,
            "missive_type": self.missive_type,
            "build_target_processors": list(self.build_target_processors or []),
            "config": config_data,
            "attachments": attachments,
        }

    def get_browser_preview_path(self) -> str:
        """Preview URL of this step. Empty when the step is not saved yet."""
        if not self.pk or not self.campaign_id:
            return ""
        from django.urls import reverse

        return reverse("django_pymissive:preview_campaign_step", args=[self.pk])


class CampaignStepTypeManager(CampaignStepManager):
    def get_queryset(self):
        return super().get_queryset().filter(missive_type=self.model.campaign_step_type)


class TypedCampaignStepMixin:
    campaign_step_type: ClassVar[str] = ""

    def save(self, *args, **kwargs):
        self.missive_type = self.campaign_step_type
        super().save(*args, **kwargs)  # type: ignore[misc]


class PostalCampaignStepMixin:
    @property
    def first_document(self):
        return self.body_rich

    @first_document.setter
    def first_document(self, value):
        self.body_rich = value

    @property
    def first_document_snapshot_html(self):
        return self.body_rich_snapshot_html

    @first_document_snapshot_html.setter
    def first_document_snapshot_html(self, value):
        self.body_rich_snapshot_html = value

    @property
    def first_document_snapshot_html_read_more(self):
        return snapshot_html_read_more(self.body_rich_snapshot_html)


class EmailCampaignStep(TypedCampaignStepMixin, CampaignStep):
    campaign_step_type: ClassVar[str] = MissiveType.EMAIL
    objects: ClassVar[CampaignStepTypeManager] = CampaignStepTypeManager()

    class Meta:
        proxy = True
        verbose_name = _("Email campaign step")
        verbose_name_plural = _("Email campaign steps")


class EmailMarketingCampaignStep(TypedCampaignStepMixin, CampaignStep):
    campaign_step_type: ClassVar[str] = MissiveType.EMAIL_MARKETING
    objects: ClassVar[CampaignStepTypeManager] = CampaignStepTypeManager()

    class Meta:
        proxy = True
        verbose_name = _("Marketing email campaign step")
        verbose_name_plural = _("Marketing email campaign steps")


class EreCampaignStep(TypedCampaignStepMixin, CampaignStep):
    campaign_step_type: ClassVar[str] = MissiveType.ERE
    objects: ClassVar[CampaignStepTypeManager] = CampaignStepTypeManager()

    class Meta:
        proxy = True
        verbose_name = _("Electronic registered email campaign step")
        verbose_name_plural = _("Electronic registered email campaign steps")


class SmsCampaignStep(TypedCampaignStepMixin, CampaignStep):
    campaign_step_type: ClassVar[str] = MissiveType.SMS
    objects: ClassVar[CampaignStepTypeManager] = CampaignStepTypeManager()

    class Meta:
        proxy = True
        verbose_name = _("SMS campaign step")
        verbose_name_plural = _("SMS campaign steps")


class RcsCampaignStep(TypedCampaignStepMixin, CampaignStep):
    campaign_step_type: ClassVar[str] = MissiveType.RCS
    objects: ClassVar[CampaignStepTypeManager] = CampaignStepTypeManager()

    class Meta:
        proxy = True
        verbose_name = _("RCS campaign step")
        verbose_name_plural = _("RCS campaign steps")


class VoiceCallCampaignStep(TypedCampaignStepMixin, CampaignStep):
    campaign_step_type: ClassVar[str] = MissiveType.VOICE_CALL
    objects: ClassVar[CampaignStepTypeManager] = CampaignStepTypeManager()

    class Meta:
        proxy = True
        verbose_name = _("Voice call campaign step")
        verbose_name_plural = _("Voice call campaign steps")


class LetterCampaignStep(PostalCampaignStepMixin, TypedCampaignStepMixin, CampaignStep):
    campaign_step_type: ClassVar[str] = MissiveType.LETTER
    objects: ClassVar[CampaignStepTypeManager] = CampaignStepTypeManager()

    class Meta:
        proxy = True
        verbose_name = _("Letter campaign step")
        verbose_name_plural = _("Letter campaign steps")


class RegisteredLetterCampaignStep(PostalCampaignStepMixin, TypedCampaignStepMixin, CampaignStep):
    campaign_step_type: ClassVar[str] = MissiveType.REGISTERED_LETTER
    objects: ClassVar[CampaignStepTypeManager] = CampaignStepTypeManager()

    class Meta:
        proxy = True
        verbose_name = _("Registered letter campaign step")
        verbose_name_plural = _("Registered letter campaign steps")


class HandDeliveryCampaignStep(PostalCampaignStepMixin, TypedCampaignStepMixin, CampaignStep):
    campaign_step_type: ClassVar[str] = MissiveType.HAND_DELIVERY
    objects: ClassVar[CampaignStepTypeManager] = CampaignStepTypeManager()

    class Meta:
        proxy = True
        verbose_name = _("Hand delivery campaign step")
        verbose_name_plural = _("Hand delivery campaign steps")


class NotificationCampaignStep(TypedCampaignStepMixin, CampaignStep):
    campaign_step_type: ClassVar[str] = MissiveType.NOTIFICATION
    objects: ClassVar[CampaignStepTypeManager] = CampaignStepTypeManager()

    class Meta:
        proxy = True
        verbose_name = _("Notification campaign step")
        verbose_name_plural = _("Notification campaign steps")


class PushNotificationCampaignStep(TypedCampaignStepMixin, CampaignStep):
    campaign_step_type: ClassVar[str] = MissiveType.PUSH_NOTIFICATION
    objects: ClassVar[CampaignStepTypeManager] = CampaignStepTypeManager()

    class Meta:
        proxy = True
        verbose_name = _("Push notification campaign step")
        verbose_name_plural = _("Push notification campaign steps")


class BrandedCampaignStep(TypedCampaignStepMixin, CampaignStep):
    campaign_step_type: ClassVar[str] = MissiveType.BRANDED
    objects: ClassVar[CampaignStepTypeManager] = CampaignStepTypeManager()

    class Meta:
        proxy = True
        verbose_name = _("Branded campaign step")
        verbose_name_plural = _("Branded campaign steps")


PhoneCampaignStep = SmsCampaignStep
PostalCampaignStep = LetterCampaignStep
