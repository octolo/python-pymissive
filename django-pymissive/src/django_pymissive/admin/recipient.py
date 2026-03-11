"""Admin for MissiveRecipient model."""

from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from django_boosted import AdminBoostModel

from ..models.recipient import (
    MissiveRecipient,
    MissiveRecipientEmail,
    MissiveRecipientPhone,
    MissiveRecipientAddress,
    MissiveRecipientNotification,
)
from ..models.choices import get_missive_style
from django.utils.html import format_html


class MissiveRecipientInline(admin.TabularInline):
    """Inline for missive recipients."""

    model = MissiveRecipient
    extra = 0
    readonly_fields = ["sent_at", "delivered_at"]
    fields = [
        "recipient_type",
        "status",
        "name",
        "email",
        "phone",
        "address",
        "notification_id",
        "external_id",
        "sent_at",
        "delivered_at",
    ]

class MissiveRecipientEmailInline(admin.TabularInline):
    """Inline for missive recipient emails."""

    model = MissiveRecipientEmail
    extra = 0
    readonly_fields = ["created_at", "updated_at", "sent_at", "delivered_at"]
    fields = [
        "recipient_type",
        "status",
        "name",
        "email",
        "external_id",
        "sent_at",
        "delivered_at",
    ]

class MissiveRecipientPhoneInline(admin.TabularInline):
    """Inline for missive recipient phones."""

    model = MissiveRecipientPhone
    extra = 0
    readonly_fields = ["created_at", "updated_at", "sent_at", "delivered_at"]
    fields = [
        "recipient_type",
        "status",
        "name",
        "phone",
        "external_id",
        "sent_at",
        "delivered_at",
    ]

class MissiveRecipientAddressInline(admin.TabularInline):
    """Inline for missive recipient addresses."""

    model = MissiveRecipientAddress
    extra = 0
    readonly_fields = ["created_at", "updated_at", "sent_at", "delivered_at"]
    fields = [
        "recipient_type",
        "status",
        "name",
        "address",
        "external_id",
        "sent_at",
        "delivered_at",
    ]

class MissiveRecipientNotificationInline(admin.TabularInline):
    """Inline for missive recipient notifications."""

    model = MissiveRecipientNotification
    extra = 0
    readonly_fields = ["created_at", "updated_at", "sent_at", "delivered_at"]
    fields = [
        "recipient_type",
        "status",
        "name",
        "notification_id",
        "external_id",
        "sent_at",
        "delivered_at",
    ]


@admin.register(MissiveRecipient)
class MissiveRecipientAdmin(AdminBoostModel):
    """Admin for missive recipients."""

    list_display = [
        "recipient_display",
        "recipient_support",
        "missive_display",
        "recipient_type_display",
    ]
    list_filter = [
        "recipient_support",
        "recipient_type",
        "status",
    ]
    search_fields = [
        "missive__subject",
        "name",
        "email",
        "phone",
        "address",
    ]
    readonly_fields = [
        "created_at",
        "updated_at",
        "status",
        "sent_at",
        "delivered_at",
    ]
    raw_id_fields = [
        "missive",
    ]

    def change_fieldsets(self):
        """Configure fieldsets for change view."""
        self.add_to_fieldset(None, ["missive", "recipient_support", "recipient_type", "status", "name"])
        self.add_to_fieldset(_("Target"), ["email", "phone", "address", "notification_id", "external_id"])
        self.add_to_fieldset(_("Comment/Timestamps"), ["comment", "created_at", "updated_at"])

    def recipient_display(self, obj):
        """Display the recipient name and email or phone or address."""
        help_text = obj.email or obj.phone or obj.address
        return self.format_with_help_text(obj.name, help_text)

    recipient_display.short_description = _("Recipient")

    def recipient_type_display(self, obj):
        """Display the recipient type."""
        recipient_type_style = get_missive_style(obj.recipient_type)
        recipient_type = self.format_label(
            obj.get_recipient_type_display(),
            size="small",
            label_type=recipient_type_style,
        )
        status_style = get_missive_style(obj.status)
        status = self.format_label(
            obj.get_status_display(), size="small", label_type=status_style
        )
        html = format_html("{} {}", recipient_type, status)
        if obj.last_event:
            event_style = get_missive_style(obj.last_event)
            event = self.format_label(
                obj.last_event_description, size="small", label_type=event_style
            )
            html = format_html("{} {}", html, event)
        return self.format_with_help_text(html, obj.last_event_date)

    recipient_type_display.short_description = _("Recipient Type")

    def missive_display(self, obj):
        """Display the missive subject."""
        return self.format_with_help_text(
            obj.missive.subject, obj.missive.get_missive_type_display()
        )

    missive_display.short_description = _("Missive")
