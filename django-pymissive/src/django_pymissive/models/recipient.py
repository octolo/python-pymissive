from django.db import models
from django.utils.translation import gettext_lazy as _

from phonenumber_field.modelfields import PhoneNumberField
from django_geoaddress.fields import GeoaddressField

from .choices import (
    MissiveRecipientType,
    MissiveStatus,
    event_to_status,
    MissiveRecipientModel,
)
from ..managers.recipient import (
    MissiveRecipientManager,
    MissiveRecipientEmailManager,
    MissiveRecipientPhoneManager,
    MissiveRecipientAddressManager,
    MissiveRecipientNotificationManager,
)


class MissiveRecipient(models.Model):
    """Recipient model"""

    missive = models.ForeignKey(
        "django_pymissive.Missive",
        on_delete=models.CASCADE,
        related_name="to_missiverecipient",
        verbose_name=_("Missive"),
        help_text=_("Missive"),
    )
    recipient_model = models.CharField(
        max_length=255,
        choices=MissiveRecipientModel.choices,
        default=MissiveRecipientModel.EMAIL,
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

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Created At"),
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("Updated At"),
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

    def get_serialized_data(self):
        return {
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "address": self.address,
            "notification_id": self.notification_id,
            "external_id": self.external_id,
        }

    @property
    def can_be_modified(self):
        return self.missive.can_be_modified

    def set_last_status(self):
        last_event = self.to_recipientevent.filter(event__isnull=False, recipient=self).order_by("-occurred_at").first()
        if last_event:
            status = event_to_status(last_event.event)
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
        if not self.recipient_model:
            self.recipient_model = MissiveRecipientModel.EMAIL
        super().save(*args, **kwargs)


class MissiveRecipientPhone(MissiveRecipient):
    objects = MissiveRecipientPhoneManager()

    class Meta:
        proxy = True
        verbose_name = _("Phone Recipient")
        verbose_name_plural = _("Phone Recipients")

    def save(self, *args, **kwargs):
        if not self.recipient_model:
            self.recipient_model = MissiveRecipientModel.PHONE
        super().save(*args, **kwargs)


class MissiveRecipientAddress(MissiveRecipient):
    objects = MissiveRecipientAddressManager()

    class Meta:
        proxy = True
        verbose_name = _("Address Recipient")
        verbose_name_plural = _("Address Recipients")

    def save(self, *args, **kwargs):
        if not self.recipient_model:
            self.recipient_model = MissiveRecipientModel.ADDRESS
        super().save(*args, **kwargs)


class MissiveRecipientNotification(MissiveRecipient):
    objects = MissiveRecipientNotificationManager()

    class Meta:
        proxy = True
        verbose_name = _("Notification Recipient")
        verbose_name_plural = _("Notification Recipients")

    def save(self, *args, **kwargs):
        if not self.recipient_model:
            self.recipient_model = MissiveRecipientModel.NOTIFICATION
        super().save(*args, **kwargs)