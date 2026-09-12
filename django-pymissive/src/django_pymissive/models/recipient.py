from django.db import models
from django.utils.translation import gettext_lazy as _

from phonenumber_field.modelfields import PhoneNumberField
from django_geoaddress.fields import GeoaddressField

from .mixins import CommentTimestampedModel
from .choices import (
    MissiveRecipientType,
    MissiveStatus,
    status_from_event_counts,
    MissiveSupport,
)
from ..managers.recipient import (
    MissiveRecipientManager,
    MissiveRecipientEmailManager,
    MissiveRecipientPhoneManager,
    MissiveRecipientAddressManager,
    MissiveRecipientApplicationManager,
)


class MissiveRecipient(CommentTimestampedModel):
    """Recipient model"""

    missive = models.ForeignKey(
        "django_pymissive.Missive",
        on_delete=models.CASCADE,
        related_name="to_missiverecipient",
        verbose_name=_("Missive"),
        help_text=_("Missive"),
    )
    recipient_support = models.CharField(
        max_length=255,
        choices=MissiveSupport.choices,
        verbose_name=_("Recipient Model"),
        help_text=_("Model of recipient"),
    )
    recipient_type = models.CharField(
        max_length=20,
        choices=MissiveRecipientType.choices,
        default=MissiveRecipientType.RECIPIENT,
        verbose_name=_("Recipient Type"),
        help_text=_("Type of recipient"),
    )
    status = models.CharField(
        max_length=20,
        choices=MissiveStatus.choices,
        default=MissiveStatus.DRAFT,
        verbose_name=_("Status"),
        help_text=_("Current status of the missive"),
    )
    name = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("Name"),
        help_text=_("Full name or company name"),
    )

    email = models.EmailField(
        blank=True,
        null=True,
        verbose_name=_("Recipient Email"),
        help_text=_("Recipient's email address"),
    )
    phone = PhoneNumberField(
        max_length=20,
        blank=True,
        null=True,
        verbose_name=_("Phone"),
        help_text=_("Phone number"),
    )
    address = GeoaddressField(
        blank=True,
        null=True,
        verbose_name=_("Address"),
        help_text=_("Address"),
    )
    notification_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name=_("Notification ID"),
        help_text=_("Notification ID"),
    )

    external_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name=_("External ID"),
        help_text=_("External identifier from the provider"),
    )
    substitute_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        db_index=True,
        verbose_name=_("Substitute ID"),
        help_text=_(
            "Provider custom_id from another internal reference. "
            "When empty, the recipient pk is used."
        ),
    )

    tracking_number = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name=_("Tracking number"),
        help_text=_(
            "Carrier tracking reference for public tracking sites "
            "(e.g. La Poste). Distinct from provider external_id."
        ),
    )

    sent_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Sent At"),
        help_text=_("When the missive was sent"),
    )
    delivered_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Delivered At"),
        help_text=_("When the missive was delivered"),
    )
    objects = MissiveRecipientManager()

    class Meta:
        verbose_name = _("Recipient")
        verbose_name_plural = _("Recipients")
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.target})"

    @property
    def target(self):
        return self.email or self.phone or self.address

    def _address_country_code(self) -> str | None:
        address = self.address
        if not address or not hasattr(address, "get"):
            return None
        code = address.get("country_code")
        if not code:
            return None
        return str(code).strip().upper() or None

    @property
    def tracking_url(self) -> str | None:
        from pymissive.postal_tracking import get_tracking_url

        return get_tracking_url(self._address_country_code(), self.tracking_number)

    def get_serialized_data(self):
        return {
            "id": str(self.id),
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "address": self.address,
            "notification_id": self.notification_id,
            "external_id": self.external_id,
            "substitute_id": self.substitute_id,
            "tracking_number": self.tracking_number,
        }

    @property
    def can_be_modified(self):
        return self.missive.can_be_modified

    def _infer_recipient_support(self) -> str:
        if self.address:
            return MissiveSupport.ADDRESS
        if self.email:
            return MissiveSupport.EMAIL
        if self.phone:
            return MissiveSupport.PHONE
        if self.notification_id:
            return MissiveSupport.APPLICATION
        missive = getattr(self, "missive", None)
        if missive is None:
            return ""
        return missive.missive_support or ""

    def save(self, *args, **kwargs):
        if not self.recipient_support:
            self.recipient_support = self._infer_recipient_support()
        super().save(*args, **kwargs)

    def set_status(self):
        from ..models.event import MissiveEvent

        success_count, processing_count, failed_count = MissiveEvent.objects.get_event_counts(recipient=self)
        status = status_from_event_counts(success_count, processing_count, failed_count)
        if status != self.status:
            self.status = status
            self.save(update_fields=["status"])

class MissiveRecipientEmail(MissiveRecipient):
    objects = MissiveRecipientEmailManager()

    class Meta:
        proxy = True
        verbose_name = _("Email Recipient")
        verbose_name_plural = _("Email Recipients")

    def save(self, *args, **kwargs):
        if not self.recipient_support:
            self.recipient_support = MissiveSupport.EMAIL
        super().save(*args, **kwargs)


class MissiveRecipientPhone(MissiveRecipient):
    objects = MissiveRecipientPhoneManager()

    class Meta:
        proxy = True
        verbose_name = _("Phone Recipient")
        verbose_name_plural = _("Phone Recipients")

    def save(self, *args, **kwargs):
        if not self.recipient_support:
            self.recipient_support = MissiveSupport.PHONE
        super().save(*args, **kwargs)


class MissiveRecipientAddress(MissiveRecipient):
    objects = MissiveRecipientAddressManager()

    class Meta:
        proxy = True
        verbose_name = _("Address Recipient")
        verbose_name_plural = _("Address Recipients")

    def save(self, *args, **kwargs):
        if not self.recipient_support:
            self.recipient_support = MissiveSupport.ADDRESS
        super().save(*args, **kwargs)


class MissiveRecipientApplication(MissiveRecipient):
    objects = MissiveRecipientApplicationManager()

    class Meta:
        proxy = True
        verbose_name = _("Application Recipient")
        verbose_name_plural = _("Application Recipients")

    def save(self, *args, **kwargs):
        if not self.recipient_support:
            self.recipient_support = MissiveSupport.APPLICATION
        super().save(*args, **kwargs)