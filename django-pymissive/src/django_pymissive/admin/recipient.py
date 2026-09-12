"""Admin for MissiveRecipient model."""

from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django_boosted import AdminBoostModel
from django_geoaddress.fields import GeoaddressField

from ..models.choices import MissiveStatus, get_missive_style
from ..models.recipient import (
    MissiveRecipient,
    MissiveRecipientAddress,
    MissiveRecipientApplication,
    MissiveRecipientEmail,
    MissiveRecipientPhone,
)


def missive_admin_locked(obj) -> bool:
    """True when the missive (or the recipient's missive) must not be edited."""
    if obj is None or not getattr(obj, "pk", None):
        return False
    missive = obj if hasattr(obj, "sender_email") else getattr(obj, "missive", None)
    if missive is None:
        return False
    if getattr(missive, "external_id", None):
        return True
    return getattr(missive, "status", None) == MissiveStatus.CANCELLED


def lock_geoaddress_formfield(formfield):
    """Keep the widget so django-geoaddress can render its native readonly layout."""
    if formfield is None:
        return
    formfield.disabled = True
    formfield.widget.attrs["readonly"] = True


class TrackingNumberLinkMixin:
    """Render ``tracking_number`` as a link to the carrier tracking page."""

    @admin.display(description=_("Tracking number"))
    def tracking_number_display(self, obj):
        if not obj:
            return "-"
        number = obj.tracking_number
        if not number:
            return "-"
        url = obj.tracking_url
        if url:
            return format_html(
                '<a href="{}" target="_blank" rel="noopener noreferrer">{}</a>',
                url,
                number,
            )
        return number


class LockedGeoaddressInlineMixin:
    """On a locked missive, freeze fields but leave GeoaddressField as a widget."""

    def get_formset(self, request, obj=None, **kwargs):
        self._lock_obj = obj
        return super().get_formset(request, obj, **kwargs)

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if not missive_admin_locked(obj):
            return readonly
        geoaddress_names = {
            field.name
            for field in self.model._meta.get_fields()
            if isinstance(field, GeoaddressField)
        }
        for name in self.fields:
            if name not in geoaddress_names and name not in readonly:
                readonly.append(name)
        return readonly

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        formfield = super().formfield_for_dbfield(db_field, request, **kwargs)
        if isinstance(db_field, GeoaddressField) and missive_admin_locked(
            getattr(self, "_lock_obj", None)
        ):
            lock_geoaddress_formfield(formfield)
        return formfield

    def get_extra(self, request, obj=None, **kwargs):
        if missive_admin_locked(obj):
            return 0
        return super().get_extra(request, obj, **kwargs)

    def has_add_permission(self, request, obj=None):
        if missive_admin_locked(obj):
            return False
        return super().has_add_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if missive_admin_locked(obj):
            return False
        return super().has_delete_permission(request, obj)


class MissiveRecipientInline(LockedGeoaddressInlineMixin, TrackingNumberLinkMixin, admin.TabularInline):
    """Inline for missive recipients."""

    model = MissiveRecipient
    extra = 0
    readonly_fields = ["sent_at", "delivered_at", "substitute_id", "tracking_number_display"]
    fields = [
        "recipient_type",
        "status",
        "name",
        "email",
        "phone",
        "address",
        "notification_id",
        "external_id",
        "substitute_id",
        "tracking_number_display",
        "sent_at",
        "delivered_at",
    ]


class MissiveRecipientEmailInline(LockedGeoaddressInlineMixin, admin.TabularInline):
    """Inline for missive recipient emails."""

    model = MissiveRecipientEmail
    extra = 0
    readonly_fields = ["created_at", "updated_at", "sent_at", "delivered_at", "substitute_id"]
    fields = [
        "recipient_type",
        "status",
        "name",
        "email",
        "external_id",
        "substitute_id",
        "sent_at",
        "delivered_at",
    ]


class MissiveRecipientPhoneInline(LockedGeoaddressInlineMixin, admin.TabularInline):
    """Inline for missive recipient phones."""

    model = MissiveRecipientPhone
    extra = 0
    readonly_fields = ["created_at", "updated_at", "sent_at", "delivered_at", "substitute_id"]
    fields = [
        "recipient_type",
        "status",
        "name",
        "phone",
        "external_id",
        "substitute_id",
        "sent_at",
        "delivered_at",
    ]


class MissiveRecipientAddressInline(LockedGeoaddressInlineMixin, TrackingNumberLinkMixin, admin.TabularInline):
    """Inline for missive recipient addresses."""

    model = MissiveRecipientAddress
    extra = 0
    readonly_fields = [
        "created_at",
        "updated_at",
        "sent_at",
        "delivered_at",
        "substitute_id",
        "tracking_number_display",
    ]
    fields = [
        "recipient_type",
        "status",
        "name",
        "address",
        "external_id",
        "substitute_id",
        "tracking_number_display",
        "sent_at",
        "delivered_at",
    ]


class MissiveRecipientApplicationInline(LockedGeoaddressInlineMixin, admin.TabularInline):
    """Inline for missive recipient applications (push, branded)."""

    model = MissiveRecipientApplication
    extra = 0
    readonly_fields = ["created_at", "updated_at", "sent_at", "delivered_at", "substitute_id"]
    fields = [
        "recipient_type",
        "status",
        "name",
        "notification_id",
        "external_id",
        "substitute_id",
        "sent_at",
        "delivered_at",
    ]


@admin.register(MissiveRecipient)
class MissiveRecipientAdmin(TrackingNumberLinkMixin, AdminBoostModel):
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
        "tracking_number",
        "external_id",
        "substitute_id",
    ]
    readonly_fields = [
        "created_at",
        "updated_at",
        "status",
        "sent_at",
        "delivered_at",
        "substitute_id",
        "tracking_number_display",
    ]
    raw_id_fields = [
        "missive",
    ]

    def change_fieldsets(self):
        """Configure fieldsets for change view."""
        self.add_to_fieldset(None, ["missive", "recipient_support", "recipient_type", "status", "name"])
        self.add_to_fieldset(
            _("Target"),
            [
                "email",
                "phone",
                "address",
                "notification_id",
                "external_id",
                "substitute_id",
                "tracking_number_display",
            ],
        )
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
                obj.last_event_reason, size="small", label_type=event_style
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
